// Aurion iOS UI Kit — shared primitives
// Load AFTER React + Babel + ios-frame.jsx
// Exposes: Btn, GoldBtn, GhostBtn, Pill, StatusBadge, Card, SectionTitle,
// Avatar, Logo, Hex, Icon, ProgressBar, Greeting, Field, RowInput, ListItem,
// BottomSheet, TabBar, NavBar, RecordButton, AURION_COLORS

const AURION = {
  navy:    '#0D1B3E',
  navyAlt: '#1A2E5C',
  navyDk:  '#0A1530',
  gold:    '#C9A84C',
  goldHi:  '#E5C97A',
  goldDk:  '#B5953D',
  canvas:  '#F8F9FA',
  surface: '#FFFFFF',
  fg1:     '#0D1B3E',
  fg2:     '#6B7280',
  fg3:     '#9AA0AC',
  border:  'rgba(13, 27, 62, 0.06)',
  borderS: 'rgba(13, 27, 62, 0.12)',
  green:   '#2E9E6A', greenBg:'#E6F5EE',
  red:     '#D9352B', redBg:'#FBE7E5',
  amber:   '#D9941F', amberBg:'#FBF1DC',
  blue:    '#2D6CDF', blueBg:'#E6EEFA',
  goldBg:  '#FBF6E6',
  goldFg:  '#8E7330',
};

const cardShadow = '0 1px 2px rgba(13, 27, 62, 0.04), 0 4px 16px rgba(13, 27, 62, 0.06)';
const sheetShadow = '0 -8px 32px rgba(13, 27, 62, 0.12)';

// ─── Hex mark ──────────────────────────────────────────────────
function Hex({ size = 36, stroke = AURION.gold, inner = AURION.navy, navyBg = false }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
      <path d="M32 4 L56 18 V46 L32 60 L8 46 V18 Z" fill="none" stroke={stroke} strokeWidth="2.5" strokeLinejoin="round"/>
      <path d="M32 10 L51 21 V43 L32 54 L13 43 V21 Z" fill="none" stroke={stroke} strokeWidth="1" opacity="0.5" strokeLinejoin="round"/>
      <path d="M22 42 L32 20 L42 42 M26 35 H38" stroke={navyBg ? '#FFFFFF' : inner} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
    </svg>
  );
}

// ─── Logo lockup ──────────────────────────────────────────────
function Logo({ dark = false, size = 1 }) {
  const wordmark = dark ? '#FFFFFF' : AURION.navy;
  const tagline = dark ? AURION.gold : AURION.fg2;
  const sz = 36 * size;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 * size }}>
      <Hex size={sz} navyBg={dark} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontFamily: 'Inter, -apple-system, sans-serif', fontSize: 22 * size, fontWeight: 600, letterSpacing: '-0.01em', color: wordmark, lineHeight: 1 }}>Aurion</div>
        <div style={{ fontFamily: 'Inter, -apple-system, sans-serif', fontSize: 9 * size, fontWeight: 600, letterSpacing: '0.16em', color: tagline }}>CLINICAL AI</div>
      </div>
    </div>
  );
}

// ─── Icon system (Lucide-style inline SVGs, SF Symbols substitute) ─
function Icon({ name, size = 22, color = 'currentColor', strokeWidth = 1.8, fill }) {
  const props = { width: size, height: size, viewBox: '0 0 24 24', fill: fill || 'none', stroke: color, strokeWidth, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'home':       return <svg {...props}><path d="M3 11l9-8 9 8v10a2 2 0 0 1-2 2h-4v-7h-6v7H5a2 2 0 0 1-2-2V11z"/></svg>;
    case 'home-fill':  return <svg {...props} fill={color} stroke="none"><path d="M3 11l9-8 9 8v10a2 2 0 0 1-2 2h-4v-7h-6v7H5a2 2 0 0 1-2-2V11z"/></svg>;
    case 'sessions':   return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="3" y1="9" x2="21" y2="9"/></svg>;
    case 'profile':    return <svg {...props}><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/></svg>;
    case 'devices':    return <svg {...props}><rect x="5" y="2" width="14" height="20" rx="3"/><circle cx="12" cy="18" r="1"/></svg>;
    case 'mic':        return <svg {...props}><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>;
    case 'camera':     return <svg {...props}><path d="M3 8h4l2-3h6l2 3h4v11H3z"/><circle cx="12" cy="13" r="3.5"/></svg>;
    case 'speaker':    return <svg {...props}><path d="M11 5L6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>;
    case 'shield':     return <svg {...props}><path d="M12 3l8 3v6c0 4.5-3.5 8.5-8 9-4.5-.5-8-4.5-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>;
    case 'chevron-r':  return <svg {...props}><polyline points="9 6 15 12 9 18"/></svg>;
    case 'chevron-l':  return <svg {...props}><polyline points="15 6 9 12 15 18"/></svg>;
    case 'chevron-d':  return <svg {...props}><polyline points="6 9 12 15 18 9"/></svg>;
    case 'check':      return <svg {...props}><polyline points="20 6 9 17 4 12"/></svg>;
    case 'check-circle': return <svg {...props}><circle cx="12" cy="12" r="10"/><polyline points="16 9 11 15 8 12"/></svg>;
    case 'pause':      return <svg {...props} fill={color}><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>;
    case 'stop':       return <svg {...props} fill={color}><rect x="6" y="6" width="12" height="12" rx="2"/></svg>;
    case 'users-2':    return <svg {...props}><circle cx="9" cy="8" r="3.5"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M14 20c0-2 2-3 4-3s4 1 4 3"/></svg>;
    case 'users-3':    return <svg {...props}><circle cx="12" cy="8" r="3.5"/><circle cx="5" cy="10" r="2.5"/><circle cx="19" cy="10" r="2.5"/><path d="M5 20c0-2.5 3-4.5 7-4.5s7 2 7 4.5M2 19c0-1.8 1.5-3 3-3M19 16c1.5 0 3 1.2 3 3"/></svg>;
    case 'grad-cap':   return <svg {...props}><path d="M2 9l10-4 10 4-10 4z"/><path d="M6 11v5c0 2 3 3.5 6 3.5s6-1.5 6-3.5v-5"/></svg>;
    case 'doc':        return <svg {...props}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="14 3 14 9 20 9"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>;
    case 'building':   return <svg {...props}><rect x="4" y="3" width="16" height="18" rx="2"/><line x1="9" y1="8" x2="9" y2="8.01"/><line x1="15" y1="8" x2="15" y2="8.01"/><line x1="9" y1="13" x2="9" y2="13.01"/><line x1="15" y1="13" x2="15" y2="13.01"/><line x1="10" y1="21" x2="14" y2="21"/></svg>;
    case 'hospital':   return <svg {...props}><path d="M3 21V8l9-5 9 5v13"/><path d="M9 21v-6h6v6M12 7v4M10 9h4"/></svg>;
    case 'heart':      return <svg {...props}><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/></svg>;
    case 'bone':       return <svg {...props}><path d="M17 10c0-2 2-2 2-4s-2-3-3.5-3-3 1-3 3c0 2-1 2-2.5 2S7.5 7 7.5 5 6 2 4.5 2 1 3 1 5s2 2 2 4M7 14c0 2-2 2-2 4s2 3 3.5 3 3-1 3-3c0-2 1-2 2.5-2s2.5 1 2.5 3 1.5 3 3 3 3.5-1 3.5-3-2-2-2-4"/></svg>;
    case 'plus':       return <svg {...props}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>;
    case 'x':          return <svg {...props}><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>;
    case 'play':       return <svg {...props} fill={color}><polygon points="6 4 20 12 6 20 6 4"/></svg>;
    case 'circle':     return <svg {...props}><circle cx="12" cy="12" r="9"/></svg>;
    case 'circle-fill':return <svg {...props} fill={color} stroke="none"><circle cx="12" cy="12" r="9"/></svg>;
    case 'arrow-r':    return <svg {...props}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/></svg>;
    case 'arrow-l':    return <svg {...props}><line x1="19" y1="12" x2="5" y2="12"/><polyline points="11 6 5 12 11 18"/></svg>;
    case 'sparkle':    return <svg {...props}><path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>;
    case 'cog':        return <svg {...props}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>;
    case 'bell':       return <svg {...props}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 0 0 4 0"/></svg>;
    case 'bluetooth':  return <svg {...props}><polyline points="6 7 18 17 12 22 12 2 18 7 6 17"/></svg>;
    case 'glasses':    return <svg {...props}><circle cx="6" cy="14" r="3"/><circle cx="18" cy="14" r="3"/><path d="M9 14h6M3 14l3-7M21 14l-3-7"/></svg>;
    case 'trainee':    return <svg {...props}><circle cx="12" cy="9" r="3.5"/><path d="M5 21c0-3.5 3-6 7-6s7 2.5 7 6"/><path d="M12 3l4 2-4 2-4-2z"/></svg>;
    default:           return <svg {...props}><circle cx="12" cy="12" r="9"/></svg>;
  }
}

// ─── Buttons ──────────────────────────────────────────────────
function GoldBtn({ children, onClick, full, size = 'md', icon, disabled, style = {} }) {
  const pad = size === 'lg' ? '16px 24px' : size === 'sm' ? '8px 16px' : '14px 22px';
  const fs = size === 'lg' ? 17 : size === 'sm' ? 14 : 16;
  return (
    <button onClick={disabled ? undefined : onClick} style={{
      background: AURION.gold, color: AURION.navy, border: 'none',
      padding: pad, borderRadius: 12, fontWeight: 600, fontSize: fs,
      fontFamily: 'inherit', cursor: disabled ? 'not-allowed' : 'pointer',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      width: full ? '100%' : undefined, opacity: disabled ? 0.4 : 1,
      boxShadow: '0 1px 2px rgba(13,27,62,0.04), 0 4px 16px rgba(201,168,76,0.24)',
      transition: 'transform 120ms ease, box-shadow 120ms ease',
      ...style,
    }}
    onMouseDown={e => e.currentTarget.style.transform = 'scale(0.97)'}
    onMouseUp={e => e.currentTarget.style.transform = 'scale(1)'}
    onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}>
      {icon && <Icon name={icon} size={18} color={AURION.navy} strokeWidth={2.2} />}
      {children}
    </button>
  );
}

function GhostBtn({ children, onClick, full, style = {} }) {
  return (
    <button onClick={onClick} style={{
      background: AURION.surface, color: AURION.navy,
      border: `1px solid ${AURION.borderS}`,
      padding: '14px 22px', borderRadius: 12, fontWeight: 600, fontSize: 16,
      fontFamily: 'inherit', cursor: 'pointer', width: full ? '100%' : undefined,
      ...style,
    }}>{children}</button>
  );
}

function TextBtn({ children, onClick, color = AURION.navy }) {
  return <button onClick={onClick} style={{
    background: 'transparent', color, border: 'none', padding: '12px 14px',
    fontWeight: 500, fontSize: 16, fontFamily: 'inherit', cursor: 'pointer',
  }}>{children}</button>;
}

// ─── Status badge ─────────────────────────────────────────────
const STATUS_MAP = {
  done:      { bg: AURION.greenBg, fg: '#1F7A4F', dot: AURION.green, label: 'Completed' },
  pending:   { bg: AURION.goldBg, fg: AURION.goldFg, dot: AURION.gold, label: 'Pending' },
  recording: { bg: AURION.red,    fg: '#FFFFFF',     dot: '#FFFFFF',    label: 'REC', heavy: true },
  archived:  { bg: '#EEF0F3',     fg: '#4A5160',     dot: AURION.fg3,   label: 'Archived' },
  exported:  { bg: AURION.blueBg, fg: '#214E9C',     dot: AURION.blue,  label: 'Exported' },
  conflict:  { bg: AURION.amberBg, fg: '#9A6E14',    dot: AURION.amber, label: 'Review' },
};
function StatusBadge({ kind = 'pending', children }) {
  const s = STATUS_MAP[kind];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', background: s.bg, color: s.fg, borderRadius: 9999,
      fontSize: 11, fontWeight: s.heavy ? 700 : 600,
      letterSpacing: s.heavy ? '0.10em' : '0.04em', whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 6, height: 6, background: s.dot, borderRadius: 9999 }} />
      {children || s.label}
    </span>
  );
}

// ─── Card ────────────────────────────────────────────────────
function Card({ children, accent, onClick, padding = 18, style = {} }) {
  return (
    <div onClick={onClick} style={{
      background: AURION.surface,
      borderRadius: 16,
      border: `1px solid ${AURION.border}`,
      borderLeft: accent ? `3px solid ${AURION.gold}` : `1px solid ${AURION.border}`,
      boxShadow: cardShadow,
      padding,
      cursor: onClick ? 'pointer' : 'default',
      transition: 'transform 140ms ease, box-shadow 140ms ease',
      ...style,
    }}>{children}</div>
  );
}

// ─── Avatar ──────────────────────────────────────────────────
function Avatar({ initials = 'SC', size = 44 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: 9999,
      background: 'radial-gradient(circle at 30% 30%, #E5C97A, #B5953D)',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      color: '#FFFFFF', fontWeight: 600, fontSize: size * 0.36,
      letterSpacing: '-0.01em', flexShrink: 0,
    }}>{initials}</div>
  );
}

// ─── Progress bar ────────────────────────────────────────────
function ProgressBar({ value = 0, color = AURION.gold, height = 4 }) {
  return (
    <div style={{ height, width: '100%', background: '#EEF0F3', borderRadius: 9999, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${value * 100}%`, background: color, borderRadius: 9999, transition: 'width 320ms cubic-bezier(0.32, 0.72, 0, 1)' }} />
    </div>
  );
}

// ─── Section title (caps) ─────────────────────────────────────
function SectionTitle({ children, action }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.10em', color: AURION.fg2, textTransform: 'uppercase' }}>{children}</div>
      {action}
    </div>
  );
}

// ─── List item (settings-style row) ───────────────────────────
function ListItem({ icon, title, value, onClick, last }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '12px 16px', cursor: onClick ? 'pointer' : 'default',
      borderBottom: last ? 'none' : `1px solid ${AURION.border}`,
    }}>
      {icon && <Icon name={icon} size={20} color={AURION.navy} strokeWidth={1.8} />}
      <div style={{ flex: 1, fontSize: 16, color: AURION.navy }}>{title}</div>
      {value && <div style={{ fontSize: 15, color: AURION.fg2 }}>{value}</div>}
      {onClick && <Icon name="chevron-r" size={18} color={AURION.fg3} strokeWidth={2} />}
    </div>
  );
}

// ─── Input field ──────────────────────────────────────────────
function Field({ label, value, onChange, placeholder, type = 'text', multiline, focused }) {
  const Comp = multiline ? 'textarea' : 'input';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {label && <label style={{ fontSize: 13, fontWeight: 500, color: AURION.fg2 }}>{label}</label>}
      <Comp type={type} value={value} placeholder={placeholder}
        onChange={onChange ? e => onChange(e.target.value) : undefined}
        style={{
          padding: '12px 14px', borderRadius: 10,
          border: focused ? `1px solid ${AURION.gold}` : `1px solid ${AURION.borderS}`,
          outline: focused ? `2px solid rgba(201,168,76,0.30)` : 'none',
          outlineOffset: 0,
          background: AURION.surface, fontSize: 16, fontFamily: 'inherit',
          color: AURION.navy, resize: 'none',
          minHeight: multiline ? 96 : undefined, width: '100%', boxSizing: 'border-box',
        }} />
    </div>
  );
}

// ─── Tab bar ──────────────────────────────────────────────────
function AurionTabBar({ active = 'home', onChange }) {
  const tabs = [
    { id: 'home',     label: 'Home',     icon: 'home' },
    { id: 'sessions', label: 'Sessions', icon: 'sessions' },
    { id: 'profile',  label: 'Profile',  icon: 'profile' },
    { id: 'devices',  label: 'Devices',  icon: 'devices' },
  ];
  return (
    <div style={{
      borderTop: `1px solid ${AURION.border}`,
      background: 'rgba(255,255,255,0.92)',
      backdropFilter: 'saturate(180%) blur(20px)',
      WebkitBackdropFilter: 'saturate(180%) blur(20px)',
      padding: '8px 0 18px',
      display: 'flex', justifyContent: 'space-around',
    }}>
      {tabs.map(t => {
        const on = t.id === active;
        return (
          <div key={t.id} onClick={() => onChange && onChange(t.id)}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, cursor: 'pointer', minWidth: 60 }}>
            <Icon name={on ? (t.icon + '-fill') : t.icon} size={24}
              color={on ? AURION.gold : AURION.fg3} strokeWidth={1.8}
              fill={on && t.icon === 'home' ? AURION.gold : 'none'} />
            <div style={{ fontSize: 10, fontWeight: on ? 600 : 500, color: on ? AURION.gold : AURION.fg3 }}>{t.label}</div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Aurion nav bar (within the device — not iOS chrome) ──────
function AurionNavBar({ title, leading, trailing, large }) {
  return (
    <div style={{
      padding: large ? '8px 20px 4px' : '6px 12px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      minHeight: 44,
    }}>
      <div style={{ minWidth: 60, display: 'flex' }}>{leading}</div>
      {!large && <div style={{ flex: 1, textAlign: 'center', fontSize: 17, fontWeight: 600, color: AURION.navy }}>{title}</div>}
      <div style={{ minWidth: 60, display: 'flex', justifyContent: 'flex-end' }}>{trailing}</div>
    </div>
  );
}

// ─── Bottom sheet wrapper ─────────────────────────────────────
function BottomSheet({ children, height }) {
  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0,
      background: AURION.surface,
      borderTopLeftRadius: 20, borderTopRightRadius: 20,
      padding: '12px 20px 28px',
      boxShadow: sheetShadow,
      maxHeight: height,
      zIndex: 30,
    }}>
      <div style={{
        width: 36, height: 5, background: 'rgba(13,27,62,0.18)',
        borderRadius: 9999, margin: '0 auto 14px',
      }} />
      {children}
    </div>
  );
}

// Expose to window for cross-script access
Object.assign(window, {
  AURION, Hex, Logo, Icon, GoldBtn, GhostBtn, TextBtn, StatusBadge,
  Card, Avatar, ProgressBar, SectionTitle, ListItem, Field,
  AurionTabBar, AurionNavBar, BottomSheet,
});
