import SwiftUI
import AVFoundation
import ReplayKit

/// Device management hub — 4th tab.
/// Audio and video sources are picked independently so a session can mix
/// hardware (e.g. Ray-Ban Meta video + iPhone mic, or iPhone for both).
struct DeviceHubView: View {
    @StateObject private var registry = CaptureSourceRegistry.shared
    @ObservedObject private var builtIn = CaptureSourceRegistry.shared.builtIn

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Devices")
                        .font(.system(size: 28, weight: .bold))
                        .tracking(-0.56)
                        .foregroundColor(.aurionNavy)
                        .padding(.bottom, -4)

                    activeSummary

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: "Audio Source")
                        audioSourcesList
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: "Video Source")
                        videoSourcesList
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: "Permissions")
                        permissionsGrid
                    }
                }
                .padding(.horizontal, AurionSpacing.edgeIPhone)
                .padding(.top, 10)
                .padding(.bottom, 20)
            }
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
                title: "Audio",
                source: registry.activeAudioSource,
                placeholder: nil
            )
            summaryCard(
                title: "Video",
                source: registry.activeVideoSource,
                placeholder: "Audio-only session"
            )
        }
    }

    private func summaryCard(title: String, source: CaptureSource?, placeholder: String?) -> some View {
        let tint = source?.status.tint ?? .aurionTextSecondary
        return VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .semibold))
                .tracking(1.0)
                .foregroundColor(.aurionTextSecondary)
            HStack(spacing: 8) {
                Image(systemName: source?.iconSystemName ?? "minus.circle")
                    .font(.system(size: 18))
                    .foregroundColor(tint)
                VStack(alignment: .leading, spacing: 1) {
                    Text(source?.displayName ?? (placeholder ?? "—"))
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(1)
                    if let source {
                        Text(source.status.label)
                            .font(.system(size: 11))
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
                label: "Camera",
                granted: builtIn.cameraPermission == .authorized
            )
            permissionCard(
                icon: "mic.fill",
                label: "Microphone",
                granted: builtIn.microphonePermission == .authorized
            )
            permissionCard(
                icon: "antenna.radiowaves.left.and.right",
                label: "Bluetooth",
                granted: true
            )
            permissionCard(
                icon: "rectangle.on.rectangle",
                label: "Screen Recording",
                granted: RPScreenRecorder.shared().isAvailable
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
                            .foregroundColor(.aurionNavy)
                        Text(label)
                            .font(.system(size: 14, weight: .medium))
                            .foregroundColor(.aurionNavy)
                            .lineLimit(1)
                    }
                    AurionStatusPill(
                        kind: granted ? .done : .archived,
                        labelOverride: granted ? "Granted" : "Denied"
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
                    Text("None")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.aurionTextPrimary)
                    Text("Audio-only session")
                        .font(.system(size: 12))
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
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.aurionTextPrimary)
                    Text(source.detail.isEmpty ? source.status.label : source.detail)
                        .font(.system(size: 12))
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
