export function AuthShell({ children, aside }: { children: React.ReactNode; aside: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh md:grid-cols-2">
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">{children}</div>
      </div>
      <div className="relative hidden overflow-hidden bg-ink text-bg md:flex">
        <div
          className="absolute inset-0 opacity-[0.16]"
          style={{
            backgroundImage: "repeating-linear-gradient(115deg, transparent 0 22px, rgba(255,255,255,0.5) 22px 23px)",
          }}
        />
        <div className="relative flex flex-col justify-between p-12">
          <div className="font-display text-2xl font-bold">Health<span className="text-accent">OS</span></div>
          {aside}
        </div>
      </div>
    </div>
  );
}
