import SwiftUI
import AVFoundation
import ReplayKit
import CoreBluetooth

/// Device management hub — 4th tab.
/// Audio and video sources are picked independently so a session can mix
/// hardware (e.g. Ray-Ban Meta video + iPhone mic, or iPhone for both).
struct DeviceHubView: View {
    @StateObject private var registry = CaptureSourceRegistry.shared
    @ObservedObject private var builtIn = CaptureSourceRegistry.shared.builtIn
    /// Matches the readable-measure clamp used by Dashboard / Inbox /
    /// Note so the four tabs feel like one app on iPad, not three
    /// stretched-phone views and one centred one.
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(L("tabs.devices"))
                        .aurionFont(28, weight: .bold, relativeTo: .title)
                        .tracking(-0.56)
                        .foregroundColor(.aurionTextPrimary)
                        .padding(.bottom, -4)

                    activeSummary

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: L("devices.audioSource"))
                        audioSourcesList
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: L("devices.videoSource"))
                        videoSourcesList
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: L("devices.permissions"))
                        permissionsGrid
                    }
                }
                .aurionScreenEdge()
                .padding(.top, 10)
                .padding(.bottom, 20)
                .frame(maxWidth: horizontalSizeClass == .regular ? 720 : .infinity)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            // Breathing room above the translucent (iOS 26 glass)
            // tab bar so the last permission tile / source row
            // doesn't read as clipped under the bar.
            .contentMargins(.bottom, 24, for: .scrollContent)
            .background(Color.aurionBackground)
            .navigationBarHidden(true)
            .onAppear {
                builtIn.refreshPermissions()
            }
        }
    }

    // MARK: - Active summary

    /// Shows the currently selected audio + video sources side by side.
    private var activeSummary: some View {
        HStack(spacing: 12) {
            summaryCard(
                title: L("devices.audio"),
                source: registry.activeAudioSource,
                placeholder: nil
            )
            summaryCard(
                title: L("devices.video"),
                source: registry.activeVideoSource,
                // placeholder shown when no video source (audio-only)
                placeholder: L("devices.audioOnlySession")
            )
        }
    }

    private func summaryCard(title: String, source: CaptureSource?, placeholder: String?) -> some View {
        let tint = source?.status.tint ?? .aurionTextSecondary
        return VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .aurionFont(10, weight: .semibold, relativeTo: .caption2)
                .tracking(1.0)
                .foregroundColor(.aurionTextSecondary)
            HStack(spacing: 8) {
                Image(systemName: source?.iconSystemName ?? "minus.circle")
                    .font(.system(size: 18))
                    .foregroundColor(tint)
                VStack(alignment: .leading, spacing: 1) {
                    Text(source?.displayName ?? (placeholder ?? "—"))
                        .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(1)
                    if let source {
                        Text(source.status.label)
                            .aurionFont(11, relativeTo: .caption2)
                            .foregroundColor(tint)
                            .lineLimit(1)
                    }
                }
                Spacer()
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.aurionCardBackground)
        .cornerRadius(14)
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
    }

    // MARK: - Source pickers

    private var audioSourcesList: some View {
        pickerCard {
            sourceRows(registry.audioSources, activeID: registry.activeAudioSource.id) {
                registry.setActiveAudio($0)
            }
        }
    }

    private var videoSourcesList: some View {
        pickerCard {
            VideoNoneRow(
                isActive: registry.activeVideoSource == nil,
                onTap: { registry.setActiveVideo(nil) }
            )
            if !registry.videoSources.isEmpty {
                Divider().padding(.leading, 52)
                sourceRows(registry.videoSources, activeID: registry.activeVideoSource?.id) {
                    registry.setActiveVideo($0)
                }
            }
        }
    }

    /// Shared chrome for the audio + video picker cards.
    private func pickerCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 0, content: content)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
            .aurionCardShadow()
    }

    @ViewBuilder
    private func sourceRows(_ sources: [CaptureSource], activeID: String?, onTap: @escaping (String) -> Void) -> some View {
        ForEach(Array(sources.enumerated()), id: \.element.id) { index, source in
            SourceRow(
                source: source,
                isActive: source.id == activeID,
                onTap: { onTap(source.id) }
            )
            if index < sources.count - 1 {
                Divider().padding(.leading, 52)
            }
        }
    }

    // MARK: - Permissions Grid

    private var permissionsGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            permissionCard(
                icon: "camera.fill",
                label: L("devices.permission.camera"),
                granted: builtIn.cameraPermission == .authorized
            )
            permissionCard(
                icon: "mic.fill",
                label: L("devices.permission.microphone"),
                granted: builtIn.microphonePermission == .authorized
            )
            permissionCard(
                icon: "antenna.radiowaves.left.and.right",
                label: L("devices.permission.bluetooth"),
                state: bluetoothTileState
            )
            // Screen recording isn't a user-grantable permission like
            // camera/mic — RPScreenRecorder reports system availability,
            // not an authorization decision. Label it Available/Unavailable
            // so it doesn't read as a denied permission the user must fix.
            permissionCard(
                icon: "rectangle.on.rectangle",
                label: L("devices.permission.screen"),
                state: RPScreenRecorder.shared().isAvailable ? .granted : .denied,
                grantedLabel: L("devices.available"),
                deniedLabel: L("devices.unavailable")
            )
        }
    }

    private func permissionCard(icon: String, label: String, granted: Bool) -> some View {
        Button {
            if !granted, let url = URL(string: UIApplication.openSettingsURLString) {
                UIApplication.shared.open(url)
            }
        } label: {
            AurionCard(padding: 14) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 10) {
                        Image(systemName: icon)
                            .font(.system(size: 20))
                            .foregroundColor(.aurionTextPrimary)
                        Text(label)
                            .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextPrimary)
                            .lineLimit(1)
                    }
                    AurionStatusPill(
                        kind: granted ? .done : .archived,
                        labelOverride: granted ? L("devices.granted") : L("devices.denied")
                    )
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }

    // MARK: - Three-state permission tile

    /// Tri-state so an un-prompted permission (neutral) is distinct from an
    /// explicit denial — the physician knows whether to grant on first
    /// prompt or open Settings to flip a previously-denied toggle.
    private enum PermissionTileState {
        case granted
        case denied
        case unknown

        var pillKind: AurionStatusKind {
            switch self {
            case .granted: return .done
            case .denied:  return .archived
            case .unknown: return .pending
            }
        }
    }

    /// Bluetooth authorization, read straight from CoreBluetooth — no manager
    /// instantiation and no permission prompt are triggered by this read.
    /// `notDetermined` maps to the neutral state because the system hasn't
    /// asked yet; only `.denied` / `.restricted` are actionable from Settings.
    private var bluetoothTileState: PermissionTileState {
        switch CBManager.authorization {
        case .allowedAlways:        return .granted
        case .denied, .restricted:  return .denied
        case .notDetermined:        return .unknown
        @unknown default:           return .unknown
        }
    }

    /// Tri-state variant of `permissionCard`. Mirrors the camera/mic pill
    /// chrome but distinguishes neutral/unknown from denied.
    private func permissionCard(
        icon: String,
        label: String,
        state: PermissionTileState,
        grantedLabel: String = L("devices.granted"),
        deniedLabel: String = L("devices.denied"),
        unknownLabel: String = L("devices.permission.notDetermined")
    ) -> some View {
        Button {
            // Only an explicit denial is fixable from Settings; an
            // un-prompted (unknown) permission resolves on first system
            // prompt and a granted one needs no action.
            if state == .denied, let url = URL(string: UIApplication.openSettingsURLString) {
                UIApplication.shared.open(url)
            }
        } label: {
            AurionCard(padding: 14) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 10) {
                        Image(systemName: icon)
                            .font(.system(size: 20))
                            .foregroundColor(.aurionTextPrimary)
                        Text(label)
                            .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextPrimary)
                            .lineLimit(1)
                    }
                    AurionStatusPill(
                        kind: state.pillKind,
                        labelOverride: {
                            switch state {
                            case .granted: return grantedLabel
                            case .denied:  return deniedLabel
                            case .unknown: return unknownLabel
                            }
                        }()
                    )
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Video "None" Row

/// Audio-only opt-out row. Stateless — no @ObservedObject needed because
/// it doesn't track a CaptureSource.
private struct VideoNoneRow: View {
    let isActive: Bool
    let onTap: () -> Void

    var body: some View {
        Button {
            AurionHaptics.selection()
            onTap()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9)
                        .fill(isActive ? Color.aurionGoldBg : Color.aurionFieldBackground)
                        .frame(width: 36, height: 36)
                    Image(systemName: "video.slash")
                        .font(.system(size: 16))
                        .foregroundColor(isActive ? .aurionGoldDark : .aurionTextSecondary)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(L("devices.none"))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                    Text(L("devices.audioOnlySession"))
                        .aurionFont(12, relativeTo: .caption)
                        .foregroundColor(.aurionTextSecondary)
                }
                Spacer()
                if isActive {
                    Image(systemName: "checkmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.aurionGold)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Source Row

/// Single picker row. Observes `source` directly so status/audioLevel/detail
/// updates only re-render this row, not the whole DeviceHubView.
private struct SourceRow: View {
    @ObservedObject var source: CaptureSource
    let isActive: Bool
    let onTap: () -> Void

    var body: some View {
        Button {
            AurionHaptics.selection()
            onTap()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9)
                        .fill(isActive ? Color.aurionGoldBg : Color.aurionFieldBackground)
                        .frame(width: 36, height: 36)
                    Image(systemName: source.iconSystemName)
                        .font(.system(size: 16))
                        .foregroundColor(isActive ? .aurionGoldDark : .aurionTextSecondary)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(source.displayName)
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                    Text(source.detail.isEmpty ? source.status.label : source.detail)
                        .aurionFont(12, relativeTo: .caption)
                        .foregroundColor(source.status.tint)
                        .lineLimit(2)
                }

                Spacer()

                if isActive {
                    Image(systemName: "checkmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.aurionGold)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!source.status.isSelectable)
        .opacity(source.status.isSelectable ? 1.0 : 0.55)
    }
}
