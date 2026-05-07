// Aurion iOS UI Kit — Screens
// Depends on components.jsx + ios-frame.jsx
// Exposes: LoginScreen, ProfileSetupScreen, DashboardScreen, EncounterTypeScreen,
// PreEncounterScreen, CaptureScreen, NoteReadyScreen, NoteReviewScreen,
// SessionsScreen, ProfileTabScreen, DevicesScreen

const { useState } = React;

// ─── 1. LOGIN ────────────────────────────────────────────────
function LoginScreen({ onSubmit }) {
  return (
    <div style={{
      width: '100%', height: '100%',
      background: 'linear-gradient(180deg, #1A2E5C 0%, #0D1B3E 100%)',
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      padding: '60px 24px 40px', color: '#FFFFFF',
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, marginTop: 40 }}>
        <Logo dark size={1.2} />
      </div>
      <div style={{
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.10)',
        borderRadius: 18, padding: 24,
        backdropFilter: 'blur(12px)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#B7C0D6' }}>Email</label>
            <input defaultValue="dr.chen@aurion.health" style={{
              marginTop: 6, padding: '12px 14px', borderRadius: 10,
              background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.16)',
              color: '#FFFFFF', fontSize: 15, fontFamily: 'inherit', width: '100%', boxSizing: 'border-box',
            }} />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#B7C0D6' }}>Password</label>
            <input type="password" defaultValue="••••••••••" style={{
              marginTop: 6, padding: '12px 14px', borderRadius: 10,
              background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.16)',
              color: '#FFFFFF', fontSize: 15, fontFamily: 'inherit', width: '100%', boxSizing: 'border-box',
            }} />
          </div>
          <GoldBtn full onClick={onSubmit}>Sign In</GoldBtn>
          <div style={{ textAlign: 'center', fontSize: 13, color: '#B7C0D6' }}>Forgot password?</div>
        </div>
      </div>
      <div style={{ textAlign: 'center', fontSize: 12, color: '#8590AE', letterSpacing: '0.04em' }}>
        For authorized personnel only.
      </div>
    </div>
  );
}

// ─── 2. PROFILE SETUP (5-step) ───────────────────────────────
function ProfileSetupScreen({ onDone }) {
  const [step, setStep] = useState(1);
  const [practice, setPractice] = useState('clinic');
  const [specialty, setSpecialty] = useState('orthopedic');
  const [visitTypes, setVisitTypes] = useState(['new', 'followup']);
  const [templates, setTemplates] = useState(['ortho-new', 'plastics-postop']);
  const [language, setLanguage] = useState('en');

  const toggleArr = (arr, set, val) => set(arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val]);

  const next = () => step < 5 ? setStep(step + 1) : onDone();
  const back = () => step > 1 ? setStep(step - 1) : null;

  const titles = {
    1: 'What type of practice?',
    2: 'Primary specialty?',
    3: 'Common visit types?',
    4: 'Preferred templates?',
    5: 'Output language?',
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      {/* Top bar with progress */}
      <div style={{ padding: '12px 20px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: AURION.fg2, marginBottom: 8 }}>
          <span>Step {step} of 5</span>
          <span style={{ cursor: 'pointer' }} onClick={onDone}>Skip</span>
        </div>
        <ProgressBar value={step / 5} />
      </div>

      <div style={{ flex: 1, padding: '4px 20px 20px', overflowY: 'auto' }}>
        <div style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em', color: AURION.navy, marginBottom: 24 }}>
          {titles[step]}
        </div>

        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { id: 'clinic', label: 'Clinic', sub: 'Outpatient practice', icon: 'building' },
              { id: 'surgical', label: 'Surgical Center', sub: 'Procedural facility', icon: 'heart' },
              { id: 'hospital', label: 'Hospital', sub: 'Inpatient setting', icon: 'hospital' },
            ].map(o => (
              <Card key={o.id} onClick={() => setPractice(o.id)} padding={20} style={{
                borderColor: practice === o.id ? AURION.gold : AURION.border,
                borderWidth: practice === o.id ? 2 : 1,
                borderStyle: 'solid',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div style={{
                    width: 48, height: 48, borderRadius: 12,
                    background: practice === o.id ? AURION.goldBg : '#EEF0F3',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Icon name={o.icon} size={24} color={practice === o.id ? AURION.goldDk : AURION.navy} strokeWidth={1.8} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 17, fontWeight: 600, color: AURION.navy }}>{o.label}</div>
                    <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>{o.sub}</div>
                  </div>
                  {practice === o.id && <Icon name="check-circle" size={22} color={AURION.gold} fill={AURION.gold} strokeWidth={2} />}
                </div>
              </Card>
            ))}
          </div>
        )}

        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              { id: 'orthopedic', label: 'Orthopedic Surgery' },
              { id: 'plastic', label: 'Plastic Surgery' },
              { id: 'sports', label: 'Sports Medicine' },
              { id: 'dermatology', label: 'Dermatology' },
              { id: 'pain', label: 'Pain Management' },
            ].map(o => (
              <div key={o.id} onClick={() => setSpecialty(o.id)} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '14px 16px', background: AURION.surface,
                borderRadius: 12,
                border: `1px solid ${specialty === o.id ? AURION.gold : AURION.border}`,
                cursor: 'pointer',
              }}>
                <span style={{
                  width: 20, height: 20, borderRadius: 9999,
                  border: `2px solid ${specialty === o.id ? AURION.gold : '#C6CAD2'}`,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {specialty === o.id && <span style={{ width: 10, height: 10, background: AURION.gold, borderRadius: 9999 }} />}
                </span>
                <div style={{ fontSize: 16, color: AURION.navy }}>{o.label}</div>
              </div>
            ))}
          </div>
        )}

        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {['new', 'followup', 'preop', 'postop'].map(id => {
              const labels = { new: 'New Patient', followup: 'Follow-up', preop: 'Pre-Op', postop: 'Post-Op' };
              const on = visitTypes.includes(id);
              return (
                <div key={id} onClick={() => toggleArr(visitTypes, setVisitTypes, id)} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '14px 16px', background: AURION.surface,
                  borderRadius: 12, border: `1px solid ${on ? AURION.gold : AURION.border}`,
                  cursor: 'pointer',
                }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 6,
                    background: on ? AURION.gold : 'transparent',
                    border: `2px solid ${on ? AURION.gold : '#C6CAD2'}`,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {on && <Icon name="check" size={14} color={AURION.navy} strokeWidth={3} />}
                  </span>
                  <div style={{ fontSize: 16, color: AURION.navy }}>{labels[id]}</div>
                </div>
              );
            })}
          </div>
        )}

        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              { id: 'ortho-new', label: 'Orthopedic — New Patient' },
              { id: 'ortho-postop', label: 'Orthopedic — Post-Op' },
              { id: 'plastics-postop', label: 'Plastics — Post-Op' },
              { id: 'sports-eval', label: 'Sports Medicine — Evaluation' },
              { id: 'pain-injection', label: 'Pain — Injection Note' },
            ].map(o => {
              const on = templates.includes(o.id);
              return (
                <div key={o.id} onClick={() => toggleArr(templates, setTemplates, o.id)} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '14px 16px', background: AURION.surface,
                  borderRadius: 12, border: `1px solid ${on ? AURION.gold : AURION.border}`,
                  cursor: 'pointer',
                }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 6,
                    background: on ? AURION.gold : 'transparent',
                    border: `2px solid ${on ? AURION.gold : '#C6CAD2'}`,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {on && <Icon name="check" size={14} color={AURION.navy} strokeWidth={3} />}
                  </span>
                  <div style={{ fontSize: 15, color: AURION.navy }}>{o.label}</div>
                </div>
              );
            })}
          </div>
        )}

        {step === 5 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { id: 'en', label: 'English', sub: 'United States', flag: '🇺🇸' },
              { id: 'fr', label: 'Français', sub: 'France', flag: '🇫🇷' },
            ].map(o => (
              <Card key={o.id} onClick={() => setLanguage(o.id)} padding={18} style={{
                borderColor: language === o.id ? AURION.gold : AURION.border,
                borderWidth: language === o.id ? 2 : 1,
                borderStyle: 'solid',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ fontSize: 32, lineHeight: 1 }}>{o.flag}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 17, fontWeight: 600, color: AURION.navy }}>{o.label}</div>
                    <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>{o.sub}</div>
                  </div>
                  {language === o.id && <Icon name="check-circle" size={22} color={AURION.gold} fill={AURION.gold} strokeWidth={2} />}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div style={{ padding: '12px 20px 20px', display: 'flex', gap: 12, borderTop: `1px solid ${AURION.border}`, background: AURION.surface }}>
        {step > 1 && <GhostBtn onClick={back} style={{ flex: 1 }}>Back</GhostBtn>}
        <GoldBtn onClick={next} style={{ flex: 2 }}>{step === 5 ? 'Get Started' : 'Continue'}</GoldBtn>
      </div>
    </div>
  );
}

// ─── 3. DASHBOARD ────────────────────────────────────────────
function DashboardScreen({ onStartSession, onTab }) {
  const quickStarts = [
    { specialty: 'Orthopedic Surgery', visit: 'New Patient', icon: 'bone' },
    { specialty: 'Plastic Surgery', visit: 'Post-Op', icon: 'heart' },
    { specialty: 'Orthopedic Surgery', visit: 'Follow-up', icon: 'bone' },
    { specialty: 'Plastic Surgery', visit: 'Pre-Op', icon: 'heart' },
  ];
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 20px 24px' }}>
        {/* Greeting */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', color: AURION.navy, lineHeight: 1.1 }}>
              Good morning,<br/>Dr. Chen.
            </div>
            <div style={{ fontSize: 14, color: AURION.fg2, marginTop: 8 }}>3 sessions today · 1 pending review</div>
          </div>
          <Avatar initials="SC" size={44} />
        </div>

        {/* Pending Review */}
        <div style={{ marginBottom: 20 }}>
          <SectionTitle>Pending Review</SectionTitle>
          <Card accent padding={16}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600, color: AURION.navy }}>M. Alvarez · Post-Op</div>
                <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>Recorded 11 min ago · 94% complete</div>
              </div>
              <button style={{
                background: AURION.gold, color: AURION.navy, border: 'none',
                padding: '6px 14px', borderRadius: 9999, fontWeight: 600, fontSize: 13, cursor: 'pointer',
              }}>Resume</button>
            </div>
          </Card>
        </div>

        {/* Quick Start */}
        <div style={{ marginBottom: 20 }}>
          <SectionTitle>Quick Start</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {quickStarts.map((q, i) => (
              <Card key={i} onClick={onStartSession} padding={14} style={{ minHeight: 100 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 10,
                    background: AURION.goldBg, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Icon name={q.icon} size={20} color={AURION.goldDk} strokeWidth={1.8} />
                  </div>
                  <div style={{ marginTop: 'auto' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', color: AURION.fg2, textTransform: 'uppercase' }}>{q.specialty}</div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: AURION.navy, marginTop: 3, lineHeight: 1.2 }}>{q.visit}</div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>

        {/* Recent Sessions */}
        <div>
          <SectionTitle action={<span style={{ fontSize: 13, color: AURION.gold, fontWeight: 600, cursor: 'pointer' }} onClick={() => onTab && onTab('sessions')}>See all</span>}>Recent Sessions</SectionTitle>
          <Card padding={0}>
            {[
              { name: 'J. Park · Follow-up', spec: 'Orthopedic Surgery', when: '9:14 AM', status: 'done' },
              { name: 'R. Singh · New Patient', spec: 'Plastic Surgery', when: '8:32 AM', status: 'done' },
              { name: 'L. Kovacs · Pre-Op', spec: 'Orthopedic Surgery', when: 'Yesterday', status: 'exported' },
            ].map((s, i, arr) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
                borderBottom: i < arr.length - 1 ? `1px solid ${AURION.border}` : 'none',
              }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 9, background: '#EEF0F3',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Icon name={s.spec.includes('Plastic') ? 'heart' : 'bone'} size={16} color={AURION.fg2} strokeWidth={1.8} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: AURION.navy, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
                  <div style={{ fontSize: 12, color: AURION.fg2 }}>{s.spec} · {s.when}</div>
                </div>
                <StatusBadge kind={s.status} />
              </div>
            ))}
          </Card>
        </div>
      </div>
      <AurionTabBar active="home" onChange={onTab} />
    </div>
  );
}

// ─── 4. ENCOUNTER TYPE SHEET ─────────────────────────────────
function EncounterTypeScreen({ onContinue, onBack }) {
  const [type, setType] = useState('doc-pt');
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <AurionNavBar
        title="Encounter Type"
        leading={<TextBtn onClick={onBack}>Cancel</TextBtn>}
      />
      <div style={{ flex: 1, padding: '8px 20px 20px', overflowY: 'auto' }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: AURION.navy, marginBottom: 4 }}>Who's in the room?</div>
        <div style={{ fontSize: 14, color: AURION.fg2, marginBottom: 20 }}>Aurion will adjust capture and consent accordingly.</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { id: 'doc-pt', label: 'Doctor + Patient', sub: 'Standard one-on-one visit', icon: 'users-2' },
            { id: 'team', label: 'With Team Member', sub: 'Nurse or PA also present', icon: 'users-3' },
            { id: 'trainee', label: 'With Trainee', sub: 'Resident or fellow observing', icon: 'grad-cap' },
          ].map(o => (
            <Card key={o.id} onClick={() => setType(o.id)} padding={18} style={{
              borderColor: type === o.id ? AURION.gold : AURION.border,
              borderWidth: type === o.id ? 2 : 1,
              borderStyle: 'solid',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 12,
                  background: type === o.id ? AURION.goldBg : '#EEF0F3',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Icon name={o.icon} size={22} color={type === o.id ? AURION.goldDk : AURION.navy} strokeWidth={1.8} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, fontWeight: 600, color: AURION.navy }}>{o.label}</div>
                  <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>{o.sub}</div>
                </div>
                {type === o.id && <Icon name="check-circle" size={22} color={AURION.gold} fill={AURION.gold} strokeWidth={2} />}
              </div>
              {type === 'team' && o.id === 'team' && (
                <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${AURION.border}`, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {['Nurse — A. Reyes', 'PA — D. Patel'].map(n => (
                    <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ width: 18, height: 18, borderRadius: 5, background: AURION.gold, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Icon name="check" size={12} color={AURION.navy} strokeWidth={3} />
                      </span>
                      <span style={{ fontSize: 14, color: AURION.navy }}>{n}</span>
                    </div>
                  ))}
                </div>
              )}
              {type === 'trainee' && o.id === 'trainee' && (
                <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${AURION.border}`, display: 'flex', gap: 10 }}>
                  <Field label="Name" placeholder="J. Lee" />
                  <Field label="Role" placeholder="Resident" />
                </div>
              )}
            </Card>
          ))}
        </div>
      </div>
      <div style={{ padding: '12px 20px 20px', borderTop: `1px solid ${AURION.border}`, background: AURION.surface }}>
        <GoldBtn full onClick={onContinue}>Continue</GoldBtn>
      </div>
    </div>
  );
}

// ─── 5. PRE-ENCOUNTER CONTEXT ────────────────────────────────
function PreEncounterScreen({ onStart, onSkip, onBack }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <AurionNavBar title="Context" leading={<TextBtn onClick={onBack}>Back</TextBtn>} />
      <div style={{ flex: 1, padding: '8px 20px 20px', overflowY: 'auto' }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: AURION.navy, marginBottom: 4 }}>What brings the patient in today?</div>
        <div style={{ fontSize: 14, color: AURION.fg2, marginBottom: 20 }}>Optional. Improves note accuracy.</div>
        <Field multiline placeholder="e.g. Right knee pain, 3 weeks post-op meniscus repair." focused />
        <div style={{ marginTop: 16, padding: 14, background: AURION.goldBg, borderRadius: 12, display: 'flex', gap: 10 }}>
          <Icon name="sparkle" size={20} color={AURION.goldDk} strokeWidth={1.8} />
          <div style={{ fontSize: 13, color: AURION.goldFg, lineHeight: 1.4 }}>Aurion uses this to focus the structured note. Stays on-device.</div>
        </div>
      </div>
      <div style={{ padding: '12px 20px 20px', borderTop: `1px solid ${AURION.border}`, background: AURION.surface, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <GoldBtn full onClick={onStart}>Start Session</GoldBtn>
        <button onClick={onSkip} style={{ background: 'transparent', color: AURION.navy, border: 'none', padding: 8, fontSize: 15, fontWeight: 500, fontFamily: 'inherit', cursor: 'pointer' }}>Skip Context</button>
      </div>
    </div>
  );
}

// ─── 6. CAPTURE SCREEN ───────────────────────────────────────
function CaptureScreen({ time = '02:47', onStop, consentOpen, onConfirmConsent, onCancelConsent }) {
  return (
    <div style={{
      width: '100%', height: '100%',
      background: 'radial-gradient(ellipse at top, #1A2E5C 0%, #0D1B3E 70%, #0A1530 100%)',
      color: '#FFFFFF', display: 'flex', flexDirection: 'column',
      position: 'relative',
    }}>
      {/* Top bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '58px 20px 0' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: 'rgba(255,255,255,0.10)', color: '#FFFFFF', borderRadius: 9999, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em' }}>
          <Icon name="bone" size={12} color="#FFFFFF" strokeWidth={2} />Orthopedic
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: AURION.red, color: '#FFFFFF', borderRadius: 9999, fontSize: 11, fontWeight: 700, letterSpacing: '0.10em' }}>
          <span style={{ width: 6, height: 6, background: '#FFFFFF', borderRadius: 9999, animation: 'pulse-rec 1.2s ease-in-out infinite' }} />REC
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          {['A', 'V', 'S'].map(s => (
            <span key={s} style={{
              width: 24, height: 24, borderRadius: 9999,
              background: 'rgba(255,255,255,0.10)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 600, color: AURION.gold,
            }}>{s}</span>
          ))}
        </div>
      </div>

      {/* Center timer */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: '"JetBrains Mono", ui-monospace, Menlo, monospace', fontVariantNumeric: 'tabular-nums', fontSize: 88, fontWeight: 500, letterSpacing: '-0.02em' }}>{time}</div>
        <div style={{ fontSize: 13, color: '#B7C0D6', marginTop: 6, letterSpacing: '0.04em' }}>Recording · Doctor + Patient</div>
        {/* Audio bars */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, marginTop: 28, height: 32 }}>
          {[10, 18, 26, 14, 22, 30, 16, 8, 22, 28, 12, 18].map((h, i) => (
            <div key={i} style={{ width: 3, height: h, background: AURION.gold, opacity: 0.8, borderRadius: 9999, animation: `bar 1.${i}s ease-in-out infinite alternate` }} />
          ))}
        </div>
      </div>

      {/* Bottom controls */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 40px 40px' }}>
        <button style={{
          width: 56, height: 56, borderRadius: 9999, background: 'rgba(255,255,255,0.10)',
          border: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
        }}>
          <Icon name="pause" size={22} color="#FFFFFF" />
        </button>
        <div style={{ position: 'relative' }}>
          <div style={{ position: 'absolute', inset: -10, borderRadius: 9999, background: 'radial-gradient(circle, rgba(201,168,76,0.30) 0%, rgba(201,168,76,0) 60%)', animation: 'pulse-halo 1.6s ease-in-out infinite' }} />
          <button style={{
            width: 78, height: 78, borderRadius: 9999, background: AURION.gold, border: 'none',
            boxShadow: '0 0 0 8px rgba(201,168,76,0.18), 0 12px 32px rgba(201,168,76,0.36)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', position: 'relative',
          }}>
            <span style={{ width: 30, height: 30, background: AURION.navy, borderRadius: 6 }} />
          </button>
        </div>
        <button onClick={onStop} style={{
          width: 56, height: 56, borderRadius: 9999, background: 'rgba(255,255,255,0.10)',
          border: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
        }}>
          <Icon name="stop" size={22} color="#FFFFFF" />
        </button>
      </div>

      <style>{`
        @keyframes pulse-halo { 0%, 100% { transform: scale(1); opacity: 0.9; } 50% { transform: scale(1.18); opacity: 0.4; } }
        @keyframes pulse-rec { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes bar { from { transform: scaleY(0.3); } to { transform: scaleY(1); } }
      `}</style>

      {consentOpen && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(13,27,62,0.78)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 28, zIndex: 100 }}>
          <div style={{ background: AURION.surface, borderRadius: 20, padding: 28, width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 64, height: 64, borderRadius: 16, background: AURION.goldBg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="shield" size={30} color={AURION.goldDk} strokeWidth={1.8} />
            </div>
            <div style={{ fontSize: 20, fontWeight: 600, color: AURION.navy, textAlign: 'center' }}>Confirm Patient Consent</div>
            <div style={{ fontSize: 14, color: AURION.fg2, textAlign: 'center', lineHeight: 1.45 }}>
              Confirm the patient has been informed and consents to recording for note generation.
            </div>
            <GoldBtn full onClick={onConfirmConsent}>Patient Has Consented</GoldBtn>
            <button onClick={onCancelConsent} style={{ background: 'transparent', color: AURION.fg2, border: 'none', fontSize: 14, fontFamily: 'inherit', cursor: 'pointer' }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 7. POST-ENCOUNTER SETTINGS ──────────────────────────────
function PostEncounterScreen({ onGenerate, onBack }) {
  const [tpl, setTpl] = useState('ortho-postop');
  const [lang, setLang] = useState('en');
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <AurionNavBar title="Generate Note" leading={<TextBtn onClick={onBack}>Back</TextBtn>} />
      <div style={{ flex: 1, padding: '8px 20px 20px', overflowY: 'auto' }}>
        <SectionTitle>Template</SectionTitle>
        <Card padding={0} style={{ marginBottom: 20 }}>
          {[
            { id: 'ortho-new', label: 'Orthopedic — New Patient' },
            { id: 'ortho-postop', label: 'Orthopedic — Post-Op' },
            { id: 'plastics-postop', label: 'Plastics — Post-Op' },
          ].map((o, i, arr) => (
            <div key={o.id} onClick={() => setTpl(o.id)} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px',
              borderBottom: i < arr.length - 1 ? `1px solid ${AURION.border}` : 'none', cursor: 'pointer',
            }}>
              <span style={{ fontSize: 15, color: AURION.navy }}>{o.label}</span>
              {tpl === o.id && <Icon name="check" size={18} color={AURION.gold} strokeWidth={2.5} />}
            </div>
          ))}
        </Card>

        <SectionTitle>Output Language</SectionTitle>
        <Card padding={0}>
          {[
            { id: 'en', label: 'English', flag: '🇺🇸' },
            { id: 'fr', label: 'Français', flag: '🇫🇷' },
          ].map((o, i, arr) => (
            <div key={o.id} onClick={() => setLang(o.id)} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
              borderBottom: i < arr.length - 1 ? `1px solid ${AURION.border}` : 'none', cursor: 'pointer',
            }}>
              <span style={{ fontSize: 22 }}>{o.flag}</span>
              <span style={{ flex: 1, fontSize: 15, color: AURION.navy }}>{o.label}</span>
              {lang === o.id && <Icon name="check" size={18} color={AURION.gold} strokeWidth={2.5} />}
            </div>
          ))}
        </Card>
      </div>
      <div style={{ padding: '12px 20px 20px', borderTop: `1px solid ${AURION.border}`, background: AURION.surface }}>
        <GoldBtn full onClick={onGenerate}>Generate Note</GoldBtn>
      </div>
    </div>
  );
}

// ─── 8. NOTE READY ───────────────────────────────────────────
function NoteReadyScreen({ onReview, onSave }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas, padding: '40px 24px 28px' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18 }}>
        <div style={{
          width: 96, height: 96, borderRadius: 24, background: AURION.goldBg,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 2px rgba(13,27,62,0.04), 0 12px 32px rgba(201,168,76,0.20)',
        }}>
          <Icon name="doc" size={44} color={AURION.goldDk} strokeWidth={1.6} />
        </div>
        <div style={{ fontSize: 28, fontWeight: 600, color: AURION.navy, letterSpacing: '-0.01em' }}>Note ready</div>
        <div style={{ fontSize: 15, color: AURION.fg2, textAlign: 'center', maxWidth: 280, lineHeight: 1.45 }}>
          Generated from a 12:34 encounter. 4 sections, 2 items flagged for review.
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <GoldBtn full onClick={onReview}>Review Now</GoldBtn>
        <GhostBtn full onClick={onSave}>Save for Later</GhostBtn>
      </div>
    </div>
  );
}

// ─── 9. NOTE REVIEW ──────────────────────────────────────────
function NoteReviewScreen({ onApprove, onBack }) {
  const sections = [
    { id: 'info', label: 'Patient Information', color: AURION.blue, status: 'done', n: 8, claims: 8 },
    { id: 'exam', label: 'Examination', color: AURION.green, status: 'done', n: 12, claims: 12 },
    { id: 'assess', label: 'Assessment', color: AURION.amber, status: 'conflict', n: 5, claims: 4, conflict: 1 },
    { id: 'plan', label: 'Plan', color: AURION.navy, status: 'pending', n: 6, claims: 5 },
  ];
  const [active, setActive] = useState('assess');
  const cur = sections.find(s => s.id === active);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <AurionNavBar title="Review Note" leading={<TextBtn onClick={onBack}>Back</TextBtn>} trailing={<TextBtn>Edit</TextBtn>} />

      {/* Section list */}
      <div style={{ padding: '4px 20px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sections.map(s => (
          <div key={s.id} onClick={() => setActive(s.id)} style={{
            background: AURION.surface,
            borderLeft: `3px solid ${s.color}`,
            borderTop: `1px solid ${AURION.border}`, borderRight: `1px solid ${AURION.border}`, borderBottom: `1px solid ${AURION.border}`,
            borderRadius: 10, padding: '10px 12px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            outline: active === s.id ? `2px solid ${AURION.gold}` : 'none',
            cursor: 'pointer',
          }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: AURION.navy }}>{s.label}</div>
              <div style={{ fontSize: 12, color: AURION.fg2, marginTop: 2 }}>{s.claims}/{s.n} claims · {s.conflict ? `${s.conflict} conflict` : 'clean'}</div>
            </div>
            <StatusBadge kind={s.status} />
          </div>
        ))}
      </div>

      {/* Section detail */}
      <div style={{ flex: 1, padding: '0 20px 16px', overflowY: 'auto' }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: AURION.navy, margin: '8px 0 12px' }}>{cur.label}</div>

        <div style={{
          background: AURION.amberBg, border: `1px solid rgba(217,148,31,0.30)`,
          borderRadius: 12, padding: 14, marginBottom: 12,
        }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <Icon name="circle" size={18} color={AURION.amber} strokeWidth={2.2} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#9A6E14', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Conflict</div>
              <div style={{ fontSize: 14, color: AURION.navy, lineHeight: 1.45 }}>Patient stated knee pain on the right; earlier note from 04/18 references left knee. Confirm laterality.</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button style={{ padding: '6px 12px', background: AURION.surface, border: `1px solid ${AURION.borderS}`, borderRadius: 9999, fontSize: 13, fontWeight: 600, color: AURION.navy, cursor: 'pointer' }}>Right</button>
                <button style={{ padding: '6px 12px', background: AURION.surface, border: `1px solid ${AURION.borderS}`, borderRadius: 9999, fontSize: 13, fontWeight: 600, color: AURION.navy, cursor: 'pointer' }}>Left</button>
              </div>
            </div>
          </div>
        </div>

        <Card padding={14} style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 14, color: AURION.navy, lineHeight: 1.45 }}>Likely meniscal re-injury given mechanism and exam findings.</div>
          <div style={{ marginTop: 8, padding: '8px 10px', background: AURION.canvas, borderRadius: 8, borderLeft: `2px solid ${AURION.gold}` }}>
            <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', color: AURION.fg2, textTransform: 'uppercase' }}>Source · 04:32</div>
            <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2, fontStyle: 'italic' }}>"…twisted it stepping off the curb, felt a pop, that same area as before."</div>
          </div>
        </Card>
        <Card padding={14}>
          <div style={{ fontSize: 14, color: AURION.navy, lineHeight: 1.45 }}>Differential includes patellar tendinopathy, less likely.</div>
        </Card>
      </div>

      {/* Bottom approval sheet */}
      <div style={{ padding: '14px 20px 20px', background: AURION.surface, borderTop: `1px solid ${AURION.border}`, display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ position: 'relative', width: 48, height: 48 }}>
          <svg width="48" height="48" viewBox="0 0 48 48">
            <circle cx="24" cy="24" r="20" fill="none" stroke="#EEF0F3" strokeWidth="4" />
            <circle cx="24" cy="24" r="20" fill="none" stroke={AURION.green} strokeWidth="4" strokeDasharray={`${2 * Math.PI * 20 * 0.94} ${2 * Math.PI * 20}`} strokeDashoffset="0" transform="rotate(-90 24 24)" strokeLinecap="round" />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: AURION.navy }}>94%</div>
        </div>
        <div style={{ flex: 1, fontSize: 13, color: AURION.fg2, lineHeight: 1.4 }}>1 conflict in Assessment must resolve before approval.</div>
        <GoldBtn onClick={onApprove} size="sm">Approve &amp; Sign</GoldBtn>
      </div>
    </div>
  );
}

// ─── 10. SESSIONS TAB ────────────────────────────────────────
function SessionsScreen({ onTab }) {
  const [filter, setFilter] = useState('all');
  const sessions = [
    { name: 'M. Alvarez · Post-Op', spec: 'Plastic Surgery', when: '11 min ago', status: 'pending' },
    { name: 'J. Park · Follow-up', spec: 'Orthopedic Surgery', when: '9:14 AM', status: 'done' },
    { name: 'R. Singh · New Patient', spec: 'Plastic Surgery', when: '8:32 AM', status: 'done' },
    { name: 'L. Kovacs · Pre-Op', spec: 'Orthopedic Surgery', when: 'Yesterday', status: 'exported' },
    { name: 'P. Martin · Post-Op', spec: 'Plastic Surgery', when: 'Yesterday', status: 'exported' },
    { name: 'O. Hassan · New Patient', spec: 'Orthopedic Surgery', when: '2 days ago', status: 'archived' },
  ];
  const filtered = filter === 'all' ? sessions : sessions.filter(s => s.status === filter);
  const counts = { all: sessions.length, pending: 1, done: 2, exported: 2 };
  const filters = [
    { id: 'all', label: 'All' },
    { id: 'pending', label: 'Pending' },
    { id: 'done', label: 'Completed' },
    { id: 'exported', label: 'Exported' },
  ];
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <div style={{ padding: '10px 20px 6px' }}>
        <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', color: AURION.navy, marginBottom: 14 }}>Sessions</div>
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
          {filters.map(f => {
            const on = filter === f.id;
            return (
              <span key={f.id} onClick={() => setFilter(f.id)} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '7px 14px', borderRadius: 9999, fontSize: 13, fontWeight: 600,
                background: on ? AURION.navy : AURION.surface,
                color: on ? '#FFFFFF' : AURION.navy,
                border: on ? 'none' : `1px solid ${AURION.border}`,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}>
                {f.label}
                <span style={{
                  background: on ? 'rgba(255,255,255,0.18)' : '#EEF0F3',
                  color: on ? '#FFFFFF' : AURION.fg2,
                  padding: '1px 7px', borderRadius: 9999, fontSize: 11, fontWeight: 600,
                }}>{counts[f.id]}</span>
              </span>
            );
          })}
        </div>
      </div>
      <div style={{ flex: 1, padding: '12px 20px 20px', overflowY: 'auto' }}>
        <Card padding={0}>
          {filtered.map((s, i, arr) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
              borderBottom: i < arr.length - 1 ? `1px solid ${AURION.border}` : 'none',
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: 10, background: '#EEF0F3',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <Icon name={s.spec.includes('Plastic') ? 'heart' : 'bone'} size={18} color={AURION.fg2} strokeWidth={1.8} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: AURION.navy, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
                <div style={{ fontSize: 12, color: AURION.fg2 }}>{s.spec} · {s.when}</div>
              </div>
              {s.status === 'pending'
                ? <button style={{ background: AURION.gold, color: AURION.navy, border: 'none', padding: '6px 12px', borderRadius: 9999, fontWeight: 600, fontSize: 12, cursor: 'pointer' }}>Resume</button>
                : <StatusBadge kind={s.status} />
              }
            </div>
          ))}
        </Card>
      </div>
      <AurionTabBar active="sessions" onChange={onTab} />
    </div>
  );
}

// ─── 11. PROFILE TAB ─────────────────────────────────────────
function ProfileTabScreen({ onTab }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <div style={{ flex: 1, padding: '10px 20px 24px', overflowY: 'auto' }}>
        <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', color: AURION.navy, marginBottom: 14 }}>Profile</div>

        <Card padding={20} style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <Avatar initials="SC" size={64} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 600, color: AURION.navy }}>Dr. Sarah Chen</div>
              <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>Orthopedic Surgery</div>
              <div style={{ fontSize: 12, color: AURION.fg3, marginTop: 2 }}>Westside Surgical Clinic</div>
            </div>
          </div>
        </Card>

        {[
          { title: 'Voice Profile', icon: 'mic' },
          { title: 'Practice Settings', icon: 'building' },
          { title: 'Team Members', icon: 'users-3', value: '2' },
          { title: 'Language', icon: 'speaker', value: 'English' },
          { title: 'Notifications', icon: 'bell' },
          { title: 'Privacy & Data', icon: 'shield' },
          { title: 'Consent History', icon: 'doc' },
          { title: 'Session History', icon: 'sessions' },
          { title: 'Legal', icon: 'doc', last: true },
        ].reduce((acc, item, i, arr) => {
          // group into cards by every 3 items
          if (i % 3 === 0) acc.push([]);
          acc[acc.length - 1].push({ ...item, last: i === arr.length - 1 || (i + 1) % 3 === 0 });
          return acc;
        }, []).map((group, gi) => (
          <Card key={gi} padding={0} style={{ marginBottom: 12 }}>
            {group.map((item, i) => (
              <ListItem key={i} icon={item.icon} title={item.title} value={item.value} onClick={() => {}} last={i === group.length - 1} />
            ))}
          </Card>
        ))}
      </div>
      <AurionTabBar active="profile" onChange={onTab} />
    </div>
  );
}

// ─── 12. DEVICES TAB ─────────────────────────────────────────
function DevicesScreen({ onTab }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: AURION.canvas }}>
      <div style={{ flex: 1, padding: '10px 20px 24px', overflowY: 'auto' }}>
        <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', color: AURION.navy, marginBottom: 14 }}>Devices</div>

        <SectionTitle>Active</SectionTitle>
        <Card accent padding={18} style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14, background: AURION.goldBg,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Icon name="glasses" size={28} color={AURION.goldDk} strokeWidth={1.8} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, fontWeight: 600, color: AURION.navy }}>Ray-Ban Meta</div>
              <div style={{ fontSize: 13, color: AURION.fg2, marginTop: 2 }}>Wayfarer · 92% battery</div>
            </div>
            <StatusBadge kind="done">Connected</StatusBadge>
          </div>
        </Card>

        <SectionTitle>Permissions</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 18 }}>
          {[
            { icon: 'camera', label: 'Camera', on: true },
            { icon: 'mic', label: 'Microphone', on: true },
            { icon: 'bluetooth', label: 'Bluetooth', on: true },
            { icon: 'speaker', label: 'Screen Capture', on: false },
          ].map(p => (
            <Card key={p.label} padding={14}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <Icon name={p.icon} size={20} color={AURION.navy} strokeWidth={1.8} />
                <div style={{ flex: 1, fontSize: 14, fontWeight: 500, color: AURION.navy }}>{p.label}</div>
              </div>
              <div style={{
                display: 'inline-block', padding: '3px 10px', borderRadius: 9999,
                fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
                background: p.on ? AURION.greenBg : '#EEF0F3',
                color: p.on ? '#1F7A4F' : AURION.fg2,
              }}>{p.on ? 'Granted' : 'Denied'}</div>
            </Card>
          ))}
        </div>

        <SectionTitle>Other Devices</SectionTitle>
        <Card padding={0}>
          <ListItem icon="camera" title="iPhone Camera" value="Available" onClick={() => {}} />
          <ListItem icon="bluetooth" title="AirPods Pro" value="Disconnected" onClick={() => {}} last />
        </Card>
      </div>
      <AurionTabBar active="devices" onChange={onTab} />
    </div>
  );
}

// Expose
Object.assign(window, {
  LoginScreen, ProfileSetupScreen, DashboardScreen, EncounterTypeScreen,
  PreEncounterScreen, CaptureScreen, PostEncounterScreen, NoteReadyScreen,
  NoteReviewScreen, SessionsScreen, ProfileTabScreen, DevicesScreen,
});
