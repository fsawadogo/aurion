import Card from "@/components/ui/Card";

/**
 * Placeholder so the Sidebar nav entry doesn't 404 between PR-C and
 * PR-E. PR-E replaces this with the templates list + the
 * conversational template builder.
 */
export default function PortalTemplatesPlaceholder() {
  return (
    <div className="p-6 lg:p-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold text-navy-800 mb-6">Templates</h1>
      <Card>
        <p className="text-sm text-gray-600">
          Custom note templates and the conversational builder will land
          here. Coming in the next portal release.
        </p>
      </Card>
    </div>
  );
}
