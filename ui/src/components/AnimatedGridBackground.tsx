/**
 * The room the car sits in: almost nothing. A faint warm light behind the car and a darker edge, both static. (The first
 * version drifted a grid, a perspective floor and scanlines; that was decoration, so it is gone.)
 */
export function AnimatedGridBackground() {
  return (
    <div aria-hidden data-testid="grid-background" className="pointer-events-none absolute inset-0 overflow-hidden bg-base">
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 52% 46% at 44% 56%, rgba(255,140,40,0.075), transparent 72%), radial-gradient(ellipse 90% 70% at 50% 120%, rgba(255,122,0,0.05), transparent 60%)',
        }}
      />
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse 90% 85% at 50% 50%, transparent 60%, rgba(0,0,0,0.55))' }} />
    </div>
  )
}
