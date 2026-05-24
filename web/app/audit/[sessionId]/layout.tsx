import Sidebar from "@/components/Sidebar";

export default function AuditTimelineLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:pl-64">{children}</main>
    </div>
  );
}
