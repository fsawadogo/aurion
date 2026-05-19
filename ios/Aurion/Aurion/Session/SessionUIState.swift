import Foundation

/// Single-source-of-truth for which top-level SwiftUI screen
/// ``SessionManager`` is driving. Replaces the trio of independent
/// booleans (``isProcessing``, ``showingReview``, ``showingPostEncounter``)
/// that could previously land in invalid combinations during a
/// state transition.
///
/// Mapping to the prior booleans (kept here for reviewers — the booleans
/// themselves are gone):
///
/// - ``.idle`` — capture screen visible. (was: all three booleans `false`.)
/// - ``.postEncounter`` — recording stopped, template/consent screen
///   visible. (was: `showingPostEncounter == true`.)
/// - ``.processing`` — audio uploading / note generating. (was:
///   `isProcessing == true`.)
/// - ``.noteReady`` — Stage 1 note delivered, awaiting user tap-through
///   to review. (was: `note != nil && !showingReview`.)
/// - ``.reviewing`` — note review screen visible. (was:
///   `showingReview == true`.)
enum SessionUIState: Equatable {
    case idle
    case postEncounter
    case processing
    case noteReady
    case reviewing
}
