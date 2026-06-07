import SwiftUI

/// Reusable device status card showing icon, name, status, and subtitle.
struct DeviceStatusCard: View {
    let icon: String
    let name: String
    let status: DeviceStatus
    let subtitle: String
    var onForget: (() -> Void)?

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(status.color.opacity(0.1))
                    .frame(width: 44, height: 44)
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundColor(status.color)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(name)
                    .aurionFont(15, weight: .medium, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                Text(subtitle)
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
            }

            Spacer()

            HStack(spacing: 4) {
                Circle()
                    .fill(status.color)
                    .frame(width: 8, height: 8)
                Text(status.label)
                    .aurionFont(11, weight: .medium, relativeTo: .caption2)
                    .foregroundColor(status.color)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(status.color.opacity(0.1))
            .cornerRadius(8)
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 16)
        .background(Color.aurionCardBackground)
        .cornerRadius(12)
        .swipeActions(edge: .trailing) {
            if let onForget {
                Button(L("common.forget"), role: .destructive) { onForget() }
            }
        }
        // Read the whole card as one element, and expose Forget as a
        // VoiceOver action so it's reachable outside a List (where
        // .swipeActions does nothing).
        .accessibilityElement(children: .combine)
        .accessibilityActions {
            if let onForget {
                Button(L("common.forget"), action: onForget)
            }
        }
    }
}

enum DeviceStatus {
    case connected
    case disconnected
    case scanning
    case recovering
    case unavailable

    var label: String {
        switch self {
        case .connected: return L("deviceStatus.connected")
        case .disconnected: return L("deviceStatus.disconnected")
        case .scanning: return L("deviceStatus.scanning")
        case .recovering: return L("deviceStatus.recovering")
        case .unavailable: return L("deviceStatus.unavailable")
        }
    }

    var color: Color {
        switch self {
        case .connected: return .aurionGreen
        case .disconnected: return .aurionRed
        case .scanning: return .aurionGold
        case .recovering: return .aurionAmber
        case .unavailable: return .secondary
        }
    }
}
