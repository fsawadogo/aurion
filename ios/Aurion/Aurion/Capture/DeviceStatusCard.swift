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
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.aurionTextPrimary)
                Text(subtitle)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }

            Spacer()

            HStack(spacing: 4) {
                Circle()
                    .fill(status.color)
                    .frame(width: 8, height: 8)
                Text(status.label)
                    .font(.caption2)
                    .fontWeight(.medium)
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
                Button("Forget", role: .destructive) { onForget() }
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
        case .connected: return "Connected"
        case .disconnected: return "Disconnected"
        case .scanning: return "Scanning"
        case .recovering: return "Recovering"
        case .unavailable: return "Unavailable"
        }
    }

    var color: Color {
        switch self {
        case .connected: return .green
        case .disconnected: return .red
        case .scanning: return .aurionGold
        case .recovering: return .aurionAmber
        case .unavailable: return .secondary
        }
    }
}
