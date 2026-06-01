import Card from "@/components/ui/Card";

/**
 * Placeholder so the Sidebar nav entry doesn't 404 between PR-C and
 * PR-D. PR-D replaces this with the real sessions inbox + note
 * review.
 */
export default function PortalNotesPlaceholder() {
  return (
    <div className="p-6 lg:p-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold text-navy-800 mb-6">My Notes</h1>
      <Card>
        <p className="text-sm text-gray-600">
          Your sessions and generated notes will land here. Coming in the
          next portal release.
        </p>
      </Card>
    </div>
  );
}
