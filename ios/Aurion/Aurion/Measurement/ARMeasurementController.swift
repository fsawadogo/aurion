import ARKit
import Combine
import SceneKit
import simd

/// Owns the ARKit session for the measurement instrument and turns physician
/// taps into a measured distance (wound L/W) or angle (ROM) — entirely
/// on-device (#63).
///
/// Two capture modes:
/// - **distance** (wound_length / wound_width): tap two points; the world-space
///   distance between them is the value (mm). With LiDAR the depth mesh gives a
///   metric anchor (`scale_source = lidar_depth`, high confidence); on A15
///   non-LiDAR devices ARKit world-tracking estimates scale
///   (`scale_source = world_tracking`, capped at medium).
/// - **angle** (rom_angle): tap a vertex then two ray endpoints; the angle at
///   the vertex is the value (degrees), via an AR goniometer overlay.
///
/// Nothing here uploads or interprets: it produces a `MeasurementResult` the
/// physician then confirms. The geometry constants (raycast alignment, the
/// tracking-quality → confidence mapping) are the **device-tuning surface** —
/// calibrate against the accuracy-characterization study (design §5) before any
/// patient use; the feature ships dark until then.
@MainActor
final class ARMeasurementController: NSObject, ObservableObject {
    /// Live readout while placing points (nil until enough points exist).
    @Published private(set) var liveResult: MeasurementResult?
    /// Points placed so far (screen feedback + enable/disable controls).
    @Published private(set) var placedPointCount = 0
    /// Current ARKit tracking quality, surfaced as a coaching hint.
    @Published private(set) var trackingHint: String?
    /// True once the session reported a usable LiDAR depth source.
    @Published private(set) var hasLiDAR = false

    let kind: MeasurementKind
    let sceneView = ARSCNView(frame: .zero)

    /// World-space points the physician has placed.
    private var points: [simd_float3] = []
    private var nodes: [SCNNode] = []
    private var lastTrackingState: ARCamera.TrackingState = .notAvailable

    /// Points required to complete this kind's measurement.
    private var requiredPoints: Int { kind.isAngle ? 3 : 2 }

    init(kind: MeasurementKind) {
        self.kind = kind
        super.init()
        sceneView.session.delegate = self
        sceneView.automaticallyUpdatesLighting = true
    }

    // MARK: - Session lifecycle

    func start() {
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        // Prefer the LiDAR depth mesh when the device has it — it's what makes
        // the wound path trustworthy. A15 non-LiDAR devices fall back to plain
        // world-tracking and are capped at medium confidence below.
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
            config.sceneReconstruction = .mesh
            hasLiDAR = true
        }
        sceneView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
    }

    func stop() {
        sceneView.session.pause()
    }

    // MARK: - Placement

    /// Place a point at a screen location (tap). Raycasts into the scene and
    /// records the world-space hit; recomputes the live result once enough
    /// points exist. No-op if the raycast misses (no surface under the tap).
    func placePoint(at screenPoint: CGPoint) {
        guard points.count < requiredPoints else { return }
        guard let world = raycastWorldPosition(screenPoint) else {
            trackingHint = L("measurement.hint.noSurface")
            return
        }
        points.append(world)
        addMarker(at: world)
        placedPointCount = points.count
        recomputeLiveResult()
    }

    /// Clear all placed points and start the measurement over.
    func reset() {
        points.removeAll()
        nodes.forEach { $0.removeFromParentNode() }
        nodes.removeAll()
        placedPointCount = 0
        liveResult = nil
    }

    /// The completed measurement, or nil if not enough points placed.
    var completedResult: MeasurementResult? {
        points.count == requiredPoints ? liveResult : nil
    }

    // MARK: - Geometry

    private func raycastWorldPosition(_ screenPoint: CGPoint) -> simd_float3? {
        // Estimated-plane raycast is the general path that works on both LiDAR
        // and non-LiDAR devices. (LiDAR mesh raycast is a device-tuning
        // improvement — see the type doc.)
        guard let query = sceneView.raycastQuery(
            from: screenPoint, allowing: .estimatedPlane, alignment: .any
        ) else { return nil }
        guard let hit = sceneView.session.raycast(query).first else { return nil }
        let t = hit.worldTransform.columns.3
        return simd_float3(t.x, t.y, t.z)
    }

    private func recomputeLiveResult() {
        let method: MeasurementMethod = kind.isAngle
            ? .arGoniometer
            : (hasLiDAR ? .arkitLidar : .arkitWorld)
        let scaleSource = kind.isAngle ? nil : (hasLiDAR ? "lidar_depth" : "world_tracking")

        let value: Double
        if kind.isAngle {
            guard points.count >= 3 else { liveResult = nil; return }
            value = angleDegrees(vertex: points[0], a: points[1], b: points[2])
        } else {
            guard points.count >= 2 else { liveResult = nil; return }
            value = Double(simd_distance(points[0], points[1])) * 1000.0  // m → mm
        }

        liveResult = MeasurementResult(
            kind: kind,
            value: value,
            method: method,
            confidence: currentConfidence(),
            confidenceReason: confidenceReason(),
            scaleSource: scaleSource,
            id: liveResult?.id ?? "meas_\(UUID().uuidString.prefix(12))"
        )
    }

    /// Angle at `vertex` between the rays to `a` and `b`, in degrees [0, 180].
    private func angleDegrees(vertex: simd_float3, a: simd_float3, b: simd_float3) -> Double {
        let v1 = simd_normalize(a - vertex)
        let v2 = simd_normalize(b - vertex)
        let dot = max(-1.0, min(1.0, simd_dot(v1, v2)))
        return Double(acos(dot)) * 180.0 / .pi
    }

    // MARK: - Confidence

    private func currentConfidence() -> MeasurementConfidence {
        switch lastTrackingState {
        case .normal:
            // LiDAR depth earns high; world-tracking-only is capped at medium
            // (no metric ground truth) per the design's accuracy posture.
            return hasLiDAR ? .high : .medium
        case .limited:
            return .low
        case .notAvailable:
            return .low
        @unknown default:
            return .low
        }
    }

    private func confidenceReason() -> String {
        switch lastTrackingState {
        case .normal:
            return hasLiDAR ? "lidar_depth, normal tracking" : "world_tracking, normal tracking"
        case .limited(let reason):
            return "limited tracking: \(reason)"
        default:
            return "tracking unavailable"
        }
    }

    // MARK: - Markers

    private func addMarker(at world: simd_float3) {
        let sphere = SCNSphere(radius: 0.004)
        sphere.firstMaterial?.diffuse.contents = UIColor.systemTeal
        let node = SCNNode(geometry: sphere)
        node.position = SCNVector3(world.x, world.y, world.z)
        sceneView.scene.rootNode.addChildNode(node)
        nodes.append(node)
        // Draw a connecting line between consecutive points for visual feedback.
        if let previous = nodes.dropLast().last {
            let line = lineNode(from: previous.position, to: node.position)
            sceneView.scene.rootNode.addChildNode(line)
            nodes.append(line)
        }
    }

    private func lineNode(from: SCNVector3, to: SCNVector3) -> SCNNode {
        let vector = SCNVector3(to.x - from.x, to.y - from.y, to.z - from.z)
        let distance = sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
        let cylinder = SCNCylinder(radius: 0.0012, height: CGFloat(distance))
        cylinder.firstMaterial?.diffuse.contents = UIColor.systemTeal
        let node = SCNNode(geometry: cylinder)
        node.position = SCNVector3((from.x + to.x) / 2, (from.y + to.y) / 2, (from.z + to.z) / 2)
        node.look(at: to, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        return node
    }
}

// MARK: - ARSessionDelegate

extension ARMeasurementController: ARSessionDelegate {
    nonisolated func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        // Capture the value-type tracking state here; ARCamera isn't Sendable,
        // so we must not carry it across the hop to the main actor.
        let state = camera.trackingState
        Task { @MainActor in
            self.lastTrackingState = state
            switch state {
            case .normal:
                self.trackingHint = nil
            case .limited:
                self.trackingHint = L("measurement.hint.moveSlowly")
            case .notAvailable:
                self.trackingHint = L("measurement.hint.initializing")
            @unknown default:
                self.trackingHint = nil
            }
            // Keep the live result's confidence in step with tracking changes.
            if !self.points.isEmpty { self.recomputeLiveResult() }
        }
    }
}
