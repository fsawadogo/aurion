import Sidebar from "@/components/Sidebar";

export default function UsersLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:pl-aurion-sidebar transition-[padding-left] duration-aurion ease-aurion">{children}</main>
    </div>
  );
}
