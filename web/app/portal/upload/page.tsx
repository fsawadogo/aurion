import VideoImportClient from "@/components/portal/VideoImportClient";

/**
 * Clinician encounter-video upload (VID-05). Static route shell; the client
 * component owns the upload + processing flow. Backend-gated by
 * `video_import_enabled` — calls 404 while the feature is dark.
 */
export default function UploadPage() {
  return <VideoImportClient />;
}
