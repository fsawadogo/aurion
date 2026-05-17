import Foundation

/// Wrapper over `SpeakerSeparation.generateEmbedding(from:)` so onboarding
/// and session-time tagging produce embeddings of the same 128-dim MFCC
/// shape. A separate 256-dim pipeline used to live here; the dimension
/// mismatch silently disabled speaker tagging on every session.
enum VoiceEmbeddingExtractor {
    static let dimension = SpeakerSeparation.shared.embeddingDimension

    static func extract(from fileURL: URL) -> Data? {
        guard let embedding = SpeakerSeparation.shared.generateEmbedding(from: fileURL) else {
            return nil
        }
        return embedding.withUnsafeBufferPointer { Data(buffer: $0) }
    }
}
