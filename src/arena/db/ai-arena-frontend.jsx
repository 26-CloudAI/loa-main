import { useState, useEffect, useCallback, useRef } from "react";

const API = "http://localhost:8080";

// ── 색상/테마 ──
const theme = {
  bg: "#0a0a0f",
  surface: "#12121a",
  surfaceAlt: "#1a1a28",
  border: "#2a2a3d",
  borderActive: "#6366f1",
  primary: "#6366f1",
  primaryHover: "#818cf8",
  danger: "#ef4444",
  dangerHover: "#f87171",
  success: "#22c55e",
  warning: "#f59e0b",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  textDim: "#64748b",
  accent: "#06b6d4",
};

// ── API 헬퍼 ──
async function api(path, options = {}) {
  const token = localStorage.getItem?.("arena_token") || sessionStorage.getItem?.("arena_token");
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  
  try {
    const res = await fetch(`${API}${path}`, { ...options, headers });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (e.message.includes("Failed to fetch")) {
      throw new Error("서버에 연결할 수 없습니다. run_server.py를 실행해 주세요.");
    }
    throw e;
  }
}

// ── 컴포넌트: 토스트 알림 ──
function Toast({ message, type = "info", onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [onClose]);

  const colors = {
    success: theme.success,
    error: theme.danger,
    info: theme.primary,
    warning: theme.warning,
  };

  return (
    <div style={{
      position: "fixed", top: 24, right: 24, zIndex: 9999,
      padding: "14px 22px", borderRadius: 8,
      background: theme.surface,
      borderLeft: `4px solid ${colors[type]}`,
      color: theme.text, fontSize: 14,
      boxShadow: `0 8px 32px rgba(0,0,0,0.5)`,
      animation: "slideIn 0.3s ease-out",
      maxWidth: 400,
    }}>
      {message}
    </div>
  );
}

// ── 컴포넌트: 코드 에디터 ──
function CodeEditor({ value, onChange, placeholder, height = 360 }) {
  const lines = (value || "").split("\n").length;
  return (
    <div style={{
      position: "relative", borderRadius: 8,
      border: `1px solid ${theme.border}`,
      background: "#0d0d14", overflow: "hidden",
    }}>
      <div style={{
        display: "flex", padding: "10px 14px",
        background: theme.surfaceAlt, borderBottom: `1px solid ${theme.border}`,
        fontSize: 12, color: theme.textDim, gap: 12, alignItems: "center",
      }}>
        <span style={{ color: theme.accent }}>●</span>
        <span>user_bot.py</span>
        <span style={{ marginLeft: "auto" }}>{lines} lines</span>
      </div>
      <div style={{ display: "flex" }}>
        <div style={{
          padding: "12px 8px", textAlign: "right", fontSize: 13,
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
          color: theme.textDim, userSelect: "none", lineHeight: 1.6,
          borderRight: `1px solid ${theme.border}`, minWidth: 40,
          background: "rgba(255,255,255,0.01)",
        }}>
          {Array.from({ length: Math.max(lines, 12) }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          spellCheck={false}
          style={{
            flex: 1, height, padding: "12px 16px",
            background: "transparent", color: theme.text,
            border: "none", outline: "none", resize: "vertical",
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
            fontSize: 13, lineHeight: 1.6, tabSize: 4,
          }}
        />
      </div>
    </div>
  );
}

// ── 컴포넌트: 버튼 ──
function Btn({ children, onClick, variant = "primary", disabled, style = {}, size = "md" }) {
  const [hover, setHover] = useState(false);
  const colors = {
    primary: { bg: theme.primary, hbg: theme.primaryHover },
    danger: { bg: theme.danger, hbg: theme.dangerHover },
    ghost: { bg: "transparent", hbg: "rgba(255,255,255,0.05)" },
    outline: { bg: "transparent", hbg: "rgba(99,102,241,0.1)" },
  };
  const c = colors[variant];
  const pad = size === "sm" ? "6px 14px" : size === "lg" ? "14px 28px" : "10px 20px";
  const fs = size === "sm" ? 12 : size === "lg" ? 16 : 14;

  return (
    <button
      onClick={onClick} disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: pad, borderRadius: 6, border: variant === "outline" ? `1px solid ${theme.border}` : "none",
        background: disabled ? theme.textDim : hover ? c.hbg : c.bg,
        color: variant === "ghost" ? theme.textMuted : "#fff",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: fs, fontWeight: 600,
        transition: "all 0.15s ease", opacity: disabled ? 0.5 : 1,
        ...style,
      }}
    >
      {children}
    </button>
  );
}

// ── 페이지: 로그인/회원가입 ──
function AuthPage({ onLogin, showToast }) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!username || !password) return showToast("모든 필드를 입력해 주세요.", "warning");
    setLoading(true);
    try {
      if (isRegister) {
        await api("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, password, display_name: displayName || username }),
        });
        showToast("등록 완료! 로그인해 주세요.", "success");
        setIsRegister(false);
      } else {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        sessionStorage.setItem("arena_token", data.access_token);
        sessionStorage.setItem("arena_user", JSON.stringify(data.user));
        onLogin(data.user);
        showToast(`${data.user.display_name}님, 환영합니다!`, "success");
      }
    } catch (e) {
      showToast(e.message, "error");
    }
    setLoading(false);
  };

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: `radial-gradient(ellipse at 30% 20%, rgba(99,102,241,0.08) 0%, transparent 50%),
                   radial-gradient(ellipse at 70% 80%, rgba(6,182,212,0.06) 0%, transparent 50%),
                   ${theme.bg}`,
    }}>
      <div style={{
        width: 400, padding: 40, borderRadius: 16,
        background: theme.surface, border: `1px solid ${theme.border}`,
        boxShadow: "0 24px 80px rgba(0,0,0,0.4)",
      }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{
            fontSize: 36, fontWeight: 800, letterSpacing: -1,
            background: `linear-gradient(135deg, ${theme.primary}, ${theme.accent})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>AI ARENA</div>
          <div style={{ color: theme.textDim, fontSize: 13, marginTop: 6 }}>
            코딩쟁이들의 e스포츠 플랫폼
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <input
            placeholder="아이디"
            value={username}
            onChange={e => setUsername(e.target.value)}
            style={inputStyle}
          />
          {isRegister && (
            <input
              placeholder="닉네임 (선택)"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              style={inputStyle}
            />
          )}
          <input
            type="password"
            placeholder="비밀번호"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSubmit()}
            style={inputStyle}
          />
          <Btn onClick={handleSubmit} disabled={loading} size="lg"
            style={{ width: "100%", marginTop: 8 }}>
            {loading ? "처리 중..." : isRegister ? "회원가입" : "로그인"}
          </Btn>
        </div>

        <div style={{ textAlign: "center", marginTop: 20 }}>
          <span style={{ color: theme.textDim, fontSize: 13 }}>
            {isRegister ? "이미 계정이 있나요?" : "계정이 없나요?"}
          </span>
          <button
            onClick={() => setIsRegister(!isRegister)}
            style={{
              background: "none", border: "none", color: theme.primary,
              cursor: "pointer", fontSize: 13, marginLeft: 6, fontWeight: 600,
            }}
          >
            {isRegister ? "로그인" : "회원가입"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "12px 16px", borderRadius: 8, fontSize: 14,
  border: `1px solid ${theme.border}`, background: theme.surfaceAlt,
  color: theme.text, outline: "none", width: "100%", boxSizing: "border-box",
};

// ── 봇 템플릿 ──
const BOT_TEMPLATES = {
  blank: `def action(state):
    """
    매 턴마다 호출됩니다.
    state에서 정보를 읽고, 행동을 반환하세요.
    
    가능한 행동:
      STAY, MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT,
      MINE, ATTACK_UP, ATTACK_DOWN, ATTACK_LEFT, ATTACK_RIGHT,
      SHIELD
    """
    return "STAY"
`,
  miner: `def action(state):
    """채굴 중심 봇 — 광물을 찾아 이동하고 채굴합니다."""
    grid = state["vision"]["grid"]
    cx, cy = 2, 2  # 시야 중심 (5x5)
    
    # 인접 칸에 광물이 있으면 그쪽으로 이동
    dirs = [(0,-1,"MOVE_UP"), (0,1,"MOVE_DOWN"), (-1,0,"MOVE_LEFT"), (1,0,"MOVE_RIGHT")]
    for dx, dy, move in dirs:
        if grid[cy+dy][cx+dx] in ("mineral", "mineral_rare"):
            return move
    
    # 시야 내 광물 방향으로 이동
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] in ("mineral", "mineral_rare"):
                mdx, mdy = dx - cx, dy - cy
                if abs(mdx) >= abs(mdy):
                    return "MOVE_RIGHT" if mdx > 0 else "MOVE_LEFT"
                return "MOVE_DOWN" if mdy > 0 else "MOVE_UP"
    
    return "MINE"
`,
  fighter: `def action(state):
    """전투형 봇 — 적을 찾아 공격합니다."""
    grid = state["vision"]["grid"]
    cx, cy = 2, 2
    
    # 인접 적 공격
    attacks = [(0,-1,"ATTACK_UP"), (0,1,"ATTACK_DOWN"),
               (-1,0,"ATTACK_LEFT"), (1,0,"ATTACK_RIGHT")]
    for dx, dy, atk in attacks:
        if grid[cy+dy][cx+dx] == "bot_enemy":
            return atk
    
    # 적 추적
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                edx, edy = dx - cx, dy - cy
                if abs(edx) >= abs(edy):
                    return "MOVE_RIGHT" if edx > 0 else "MOVE_LEFT"
                return "MOVE_DOWN" if edy > 0 else "MOVE_UP"
    
    return "MOVE_RIGHT"
`,
};

// ── 페이지: 봇 에디터 ──
function BotEditor({ bot, onSave, onCancel, showToast }) {
  const [name, setName] = useState(bot?.name || "");
  const [code, setCode] = useState(bot?.code || BOT_TEMPLATES.blank);
  const [desc, setDesc] = useState(bot?.description || "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name.trim()) return showToast("봇 이름을 입력해 주세요.", "warning");
    if (!code.trim()) return showToast("코드를 입력해 주세요.", "warning");
    setSaving(true);
    try {
      await onSave({ name: name.trim(), code, description: desc });
    } catch (e) {
      showToast(e.message, "error");
    }
    setSaving(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ color: theme.text, fontSize: 22, fontWeight: 700, margin: 0 }}>
          {bot ? `${bot.name} 수정` : "새 봇 만들기"}
        </h2>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="ghost" onClick={onCancel}>취소</Btn>
          <Btn onClick={handleSave} disabled={saving}>
            {saving ? "저장 중..." : bot ? "업데이트" : "생성"}
          </Btn>
        </div>
      </div>

      <div style={{ display: "flex", gap: 14 }}>
        <input
          placeholder="봇 이름"
          value={name}
          onChange={e => setName(e.target.value)}
          disabled={!!bot}
          style={{ ...inputStyle, flex: 1 }}
        />
        <input
          placeholder="설명 (선택)"
          value={desc}
          onChange={e => setDesc(e.target.value)}
          style={{ ...inputStyle, flex: 2 }}
        />
      </div>

      {!bot && (
        <div style={{ display: "flex", gap: 8 }}>
          <span style={{ color: theme.textDim, fontSize: 13, alignSelf: "center" }}>템플릿:</span>
          {[["blank", "빈 봇"], ["miner", "채굴형"], ["fighter", "전투형"]].map(([key, label]) => (
            <Btn key={key} variant="outline" size="sm" onClick={() => setCode(BOT_TEMPLATES[key])}>
              {label}
            </Btn>
          ))}
        </div>
      )}

      <CodeEditor
        value={code}
        onChange={setCode}
        placeholder="def action(state): ..."
        height={420}
      />

      <div style={{
        padding: "12px 16px", borderRadius: 8,
        background: "rgba(6,182,212,0.06)",
        border: `1px solid rgba(6,182,212,0.15)`,
        fontSize: 12, color: theme.textDim, lineHeight: 1.7,
      }}>
        <strong style={{ color: theme.accent }}>action(state)</strong> 함수를 정의하세요.
        state에는 tick, my_bot(위치·에너지·점수), vision(5×5 시야), zone_boundary(자기장), leaderboard가 포함됩니다.
        반환값은 STAY, MOVE_*, MINE, ATTACK_*, SHIELD 중 하나입니다.
      </div>
    </div>
  );
}

// ── 페이지: 대시보드 ──
function Dashboard({ user, onLogout, showToast }) {
  const [bots, setBots] = useState([]);
  const [editing, setEditing] = useState(null);  // null | "new" | BotRecord
  const [loading, setLoading] = useState(true);
  const [games, setGames] = useState([]);

  // 데모 모드 (서버 없이 로컬 상태로 동작)
  const [demoMode, setDemoMode] = useState(false);

  const fetchBots = useCallback(async () => {
    try {
      const data = await api("/api/bots");
      setBots(data);
      setDemoMode(false);
    } catch {
      setDemoMode(true);
      // 데모 모드: 로컬 상태 유지
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchBots(); }, [fetchBots]);

  const handleSave = async ({ name, code, description }) => {
    if (demoMode) {
      // 데모 모드: 로컬에서만 관리
      if (editing === "new") {
        const newBot = {
          id: Date.now(), name, code, description,
          version: 1, wins: 0, losses: 0, games_played: 0,
          created_at: new Date().toISOString(),
        };
        setBots(prev => [newBot, ...prev]);
      } else {
        setBots(prev => prev.map(b =>
          b.id === editing.id ? { ...b, code, description, version: b.version + 1 } : b
        ));
      }
      showToast(editing === "new" ? "봇이 생성되었습니다." : "봇이 업데이트되었습니다.", "success");
      setEditing(null);
      return;
    }

    if (editing === "new") {
      await api("/api/bots", {
        method: "POST",
        body: JSON.stringify({ name, code, description }),
      });
      showToast("봇이 생성되었습니다.", "success");
    } else {
      await api(`/api/bots/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify({ code, description }),
      });
      showToast("봇이 업데이트되었습니다.", "success");
    }
    setEditing(null);
    fetchBots();
  };

  const handleDelete = async (bot) => {
    if (demoMode) {
      setBots(prev => prev.filter(b => b.id !== bot.id));
      showToast("봇이 삭제되었습니다.", "success");
      return;
    }
    try {
      await api(`/api/bots/${bot.id}`, { method: "DELETE" });
      showToast("봇이 삭제되었습니다.", "success");
      fetchBots();
    } catch (e) {
      showToast(e.message, "error");
    }
  };

  if (editing) {
    return (
      <Layout user={user} onLogout={onLogout} demoMode={demoMode}>
        <BotEditor
          bot={editing === "new" ? null : editing}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
          showToast={showToast}
        />
      </Layout>
    );
  }

  return (
    <Layout user={user} onLogout={onLogout} demoMode={demoMode}>
      {/* 봇 목록 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ color: theme.text, fontSize: 22, fontWeight: 700, margin: 0 }}>
          내 봇 <span style={{ color: theme.textDim, fontSize: 14, fontWeight: 400 }}>({bots.length})</span>
        </h2>
        <Btn onClick={() => setEditing("new")}>+ 새 봇 만들기</Btn>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60, color: theme.textDim }}>로딩 중...</div>
      ) : bots.length === 0 ? (
        <div style={{
          textAlign: "center", padding: 60,
          border: `2px dashed ${theme.border}`, borderRadius: 12,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🤖</div>
          <div style={{ color: theme.textMuted, fontSize: 16, marginBottom: 16 }}>
            아직 봇이 없습니다
          </div>
          <Btn onClick={() => setEditing("new")}>첫 번째 봇 만들기</Btn>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {bots.map(bot => (
            <div key={bot.id} style={{
              padding: "16px 20px", borderRadius: 10,
              background: theme.surfaceAlt, border: `1px solid ${theme.border}`,
              display: "flex", alignItems: "center", gap: 16,
              transition: "border-color 0.15s",
            }}>
              <div style={{
                width: 42, height: 42, borderRadius: 8,
                background: `linear-gradient(135deg, ${theme.primary}40, ${theme.accent}40)`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 18, fontWeight: 700, color: theme.primary,
              }}>
                {bot.name[0]?.toUpperCase()}
              </div>

              <div style={{ flex: 1 }}>
                <div style={{ color: theme.text, fontWeight: 600, fontSize: 15 }}>
                  {bot.name}
                  <span style={{ fontSize: 11, color: theme.textDim, marginLeft: 8 }}>
                    v{bot.version}
                  </span>
                </div>
                <div style={{ color: theme.textDim, fontSize: 12, marginTop: 2 }}>
                  {bot.description || "설명 없음"}
                </div>
              </div>

              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                <div style={{ textAlign: "center", minWidth: 50 }}>
                  <div style={{ color: theme.success, fontSize: 16, fontWeight: 700 }}>{bot.wins}</div>
                  <div style={{ color: theme.textDim, fontSize: 10 }}>승</div>
                </div>
                <div style={{ textAlign: "center", minWidth: 50 }}>
                  <div style={{ color: theme.danger, fontSize: 16, fontWeight: 700 }}>{bot.losses}</div>
                  <div style={{ color: theme.textDim, fontSize: 10 }}>패</div>
                </div>
                <div style={{ textAlign: "center", minWidth: 50 }}>
                  <div style={{ color: theme.text, fontSize: 16, fontWeight: 700 }}>{bot.games_played}</div>
                  <div style={{ color: theme.textDim, fontSize: 10 }}>판</div>
                </div>
              </div>

              <div style={{ display: "flex", gap: 6 }}>
                <Btn variant="outline" size="sm" onClick={() => setEditing(bot)}>수정</Btn>
                <Btn variant="ghost" size="sm" onClick={() => handleDelete(bot)}
                  style={{ color: theme.danger }}>삭제</Btn>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 퀵 플레이 안내 */}
      <div style={{
        marginTop: 32, padding: "24px 28px", borderRadius: 12,
        background: `linear-gradient(135deg, rgba(99,102,241,0.08), rgba(6,182,212,0.06))`,
        border: `1px solid rgba(99,102,241,0.15)`,
      }}>
        <h3 style={{ color: theme.text, fontSize: 16, margin: "0 0 8px 0" }}>퀵 플레이</h3>
        <p style={{ color: theme.textMuted, fontSize: 13, margin: "0 0 14px 0", lineHeight: 1.6 }}>
          봇을 선택하고 바로 게임을 시작하세요. 빈 슬롯은 AI 봇이 채웁니다.
        </p>
        {bots.length > 0 ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {bots.map(bot => (
              <Btn key={bot.id} variant="outline" size="sm"
                onClick={() => showToast(`${bot.name}으로 게임 시작! (서버 연결 시 동작)`, "info")}>
                {bot.name}으로 참전
              </Btn>
            ))}
          </div>
        ) : (
          <span style={{ color: theme.textDim, fontSize: 13 }}>먼저 봇을 만들어 주세요.</span>
        )}
      </div>
    </Layout>
  );
}

// ── 레이아웃 ──
function Layout({ children, user, onLogout, demoMode }) {
  return (
    <div style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse at 20% 0%, rgba(99,102,241,0.05) 0%, transparent 50%),
                   ${theme.bg}`,
    }}>
      {/* 헤더 */}
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 32px", height: 56,
        borderBottom: `1px solid ${theme.border}`,
        background: "rgba(10,10,15,0.8)", backdropFilter: "blur(12px)",
        position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{
          fontSize: 20, fontWeight: 800, letterSpacing: -0.5,
          background: `linear-gradient(135deg, ${theme.primary}, ${theme.accent})`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
        }}>
          AI ARENA
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {demoMode && (
            <span style={{
              fontSize: 11, color: theme.warning, padding: "3px 10px",
              background: "rgba(245,158,11,0.1)", borderRadius: 12,
            }}>
              데모 모드
            </span>
          )}
          <span style={{ color: theme.textMuted, fontSize: 13 }}>
            {user?.display_name || user?.username}
          </span>
          <Btn variant="ghost" size="sm" onClick={onLogout}>로그아웃</Btn>
        </div>
      </header>

      {/* 콘텐츠 */}
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "28px 24px" }}>
        {children}
      </main>
    </div>
  );
}

// ── 메인 앱 ──
export default function App() {
  const [user, setUser] = useState(() => {
    try {
      const saved = sessionStorage.getItem?.("arena_user");
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });
  const [toast, setToast] = useState(null);

  const showToast = useCallback((message, type = "info") => {
    setToast({ message, type, key: Date.now() });
  }, []);

  const handleLogout = () => {
    sessionStorage.removeItem("arena_token");
    sessionStorage.removeItem("arena_user");
    setUser(null);
    showToast("로그아웃 되었습니다.", "info");
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        ::selection { background: ${theme.primary}40; }
        input:focus { border-color: ${theme.borderActive} !important; }
        textarea:focus { outline: none; }
        @keyframes slideIn {
          from { transform: translateX(100px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${theme.border}; border-radius: 3px; }
      `}</style>

      {toast && (
        <Toast
          key={toast.key}
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {user ? (
        <Dashboard user={user} onLogout={handleLogout} showToast={showToast} />
      ) : (
        <AuthPage onLogin={setUser} showToast={showToast} />
      )}
    </>
  );
}
