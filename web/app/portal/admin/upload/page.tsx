import VideoImportClient from "@/components/portal/VideoImportClient";

/**
 * Admin / eval encounter-video upload (VID-10). Same component as the
 * clinician surface, in admin mode: posts to /admin/video-imports and
 * redirects to the admin /sessions detail on completion. Backend-gated by
 * `video_import_enabled`.
 */
export default function AdminUploadPage() {
  return <VideoImportClient surface="admin" />;
}
