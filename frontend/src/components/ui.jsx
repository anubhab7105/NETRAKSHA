import React from 'react';
import { AlertTriangle, CheckCircle2, ShieldAlert, Info, XCircle } from 'lucide-react';
import { VERIFICATION_STEPS } from '../config/constants';



export function StatusBadge({ tone = 'grey', icon, children, className = '' }) {
  return (
    <span className={`gov-badge gov-badge-${tone} ${className}`}>
      {icon}
      {children}
    </span>
  );
}

export function VerdictBadge({ verdict }) {
  if (verdict === 'Green')
    return <StatusBadge tone="green" icon={<CheckCircle2 size={13} aria-hidden="true" />}>VERIFIED · LOW RISK</StatusBadge>;
  if (verdict === 'Yellow')
    return <StatusBadge tone="amber" icon={<AlertTriangle size={13} aria-hidden="true" />}>MANUAL REVIEW</StatusBadge>;
  if (verdict === 'Red')
    return <StatusBadge tone="red" icon={<ShieldAlert size={13} aria-hidden="true" />}>HIGH RISK · ESCALATE</StatusBadge>;
  return <StatusBadge tone="grey" icon={<Info size={13} aria-hidden="true" />}>{String(verdict || 'UNKNOWN').toUpperCase()}</StatusBadge>;
}


export function CheckRow({ label, state, detail }) {
  const map = {
    PASS: { tone: 'green', icon: <CheckCircle2 size={14} aria-hidden="true" />, text: 'PASS' },
    REVIEW: { tone: 'amber', icon: <AlertTriangle size={14} aria-hidden="true" />, text: 'REVIEW' },
    FAIL: { tone: 'red', icon: <XCircle size={14} aria-hidden="true" />, text: 'FAIL' },
    NONE: { tone: 'green', icon: <CheckCircle2 size={14} aria-hidden="true" />, text: 'NONE' },
    NA: { tone: 'grey', icon: <Info size={14} aria-hidden="true" />, text: 'N/A' },
  };
  const s = map[state] || map.NA;
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[#EAEDEF] py-2.5 last:border-0">
      <div className="min-w-0">
        <p className="text-[13px] font-semibold tracking-wide text-[#172033]">{label}</p>
        {detail && <p className="mt-0.5 text-xs text-[#667085]">{detail}</p>}
      </div>
      <StatusBadge tone={s.tone} icon={s.icon}>{s.text}</StatusBadge>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="gov-page-title">{title}</h1>
        {subtitle && <p className="gov-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

export function KpiCard({ label, value, sub, icon, accent = '#1769AA' }) {
  return (
    <div className="gov-card-padded">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[#667085]">{label}</p>
          <p className="mt-1.5 text-[26px] font-bold leading-none text-[#172033]">{value}</p>
          {sub && <p className="mt-1.5 text-xs text-[#667085]">{sub}</p>}
        </div>
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#D9DEE7] bg-[#F1F4F9]"
          style={{ color: accent }}
          aria-hidden="true"
        >
          {icon}
        </div>
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-[#EEF1F6]" aria-hidden="true">
        <div className="h-full w-full origin-left rounded-full opacity-20" style={{ background: accent }} />
      </div>
    </div>
  );
}


export function WorkflowSteps({ activeIndex = 0, compact = false }) {
  return (
    <ol
      aria-label="Verification workflow progress"
      className={`flex items-start gap-1 overflow-x-auto pb-1 ${compact ? '' : 'py-1'}`}
    >
      {VERIFICATION_STEPS.map((label, i) => {
        const done = i < activeIndex;
        const current = i === activeIndex;
        return (
          <li key={label} className="flex min-w-0 flex-1 items-start" style={{ minWidth: 92 }}>
            <div className="flex w-full flex-col items-center gap-1.5 text-center">
              <span className={`gov-step-dot ${done ? 'gov-step-done' : current ? 'gov-step-current' : ''}`} aria-hidden="true">
                {done ? '✓' : i + 1}
              </span>
              <span
                className={`text-[11px] leading-tight ${current ? 'font-semibold text-[#123B66]' : done ? 'font-medium text-[#172033]' : 'text-[#98A2B3]'}`}
                aria-current={current ? 'step' : undefined}
              >
                {label}
              </span>
            </div>
            {i < VERIFICATION_STEPS.length - 1 && (
              <div className={`mx-1 mt-3 h-px flex-1 ${done ? 'bg-[#123B66]' : 'bg-[#D9DEE7]'}`} aria-hidden="true" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function GovNotice({ tone = 'blue', icon, title, children }) {
  return (
    <div className={`gov-notice gov-notice-${tone}`} role="status">
      <span className="mt-0.5 shrink-0" aria-hidden="true">{icon}</span>
      <div className="min-w-0">
        {title && <p className="text-sm font-bold">{title}</p>}
        <div className="mt-0.5 text-[13px] leading-relaxed">{children}</div>
      </div>
    </div>
  );
}
