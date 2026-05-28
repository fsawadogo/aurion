import Combine
import Foundation
import Network

/// Observes network reachability via `NWPathMonitor` so the UI can surface an
/// offline state and the `OfflineUploadQueue` can flush the moment
/// connectivity returns.
///
/// This reports *interface* reachability, not backend health — a clinic on
/// Wi-Fi with the backend unreachable still reads as "online" here, and that
/// failure is handled downstream (the upload throws `APIError.offline` /
/// `.timeout`, the queue keeps the item). The value of this monitor is the
/// offline→online *transition*, which is the trigger to retry queued work.
@MainActor
final class ReachabilityMonitor: ObservableObject {
    static let shared = ReachabilityMonitor()

    /// True when at least one network interface can carry traffic. Starts
    /// optimistic (`true`) so the UI doesn't flash an offline banner during
    /// the first path evaluation; the first `pathUpdateHandler` callback
    /// corrects it within milliseconds.
    @Published private(set) var isOnline: Bool = true

    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "com.aurion.reachability")

    /// Invoked exactly on an offline→online transition (not on the initial
    /// reading, and not on online→online refreshes). The `OfflineUploadQueue`
    /// registers here to drain itself on reconnect.
    private var onReconnect: (() async -> Void)?

    private init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let online = path.status == .satisfied
            Task { @MainActor in self?.apply(online: online) }
        }
        monitor.start(queue: queue)
    }

    /// Register the offline→online reconnect handler. Replaces any prior
    /// handler — there is a single consumer (the upload queue).
    func setReconnectHandler(_ handler: @escaping () async -> Void) {
        onReconnect = handler
    }

    private func apply(online: Bool) {
        let wasOnline = isOnline
        guard online != wasOnline else { return }
        isOnline = online
        if online {
            // offline → online: drain whatever was queued while we were dark.
            let handler = onReconnect
            Task { await handler?() }
        }
    }
}
