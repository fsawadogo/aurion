import Foundation

/// Single-source-of-truth for which top-level SwiftUI screen
/// ``SessionManager`` is driving. ContentView's dispatch cascade
/// switches on this directly — the predecessor design used three
/// independent booleans which could land in invalid combinations
/// mid-transition (e.g. ``showingReview`` and ``showingPostEncounter``
/// both true while ``note`` was nil).
///
/// - ``.idle`` — capture screen visible, no active session.
/// - ``.postEncounter`` — recording stopped, template/consent screen
///   visible.
/// - ``.processing`` — audio uploading / Stage 1 note generating.
/// - ``.noteReady`` — Stage 1 note delivered, awaiting user
///   tap-through to review.
/// - ``.reviewing`` — note review screen visible.
enum SessionUIState: Equatable {
    case idle
    case postEncounter
    case processing
    case noteReady
    case reviewing
}
