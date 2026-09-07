import { useState } from "react";

import ShopFloor from "./shopfloor/ShopFloor";
import { clearToken, getToken, getUsername, login } from "./api/client";

function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
      onDone();
    } catch {
      setError("เข้าใช้งานไม่ได้ — ตรวจชื่อผู้ใช้และรหัสผ่านอีกครั้ง");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="app login" onSubmit={submit}>
      <h1>บันทึกผลหน้างาน</h1>
      <input
        placeholder="ชื่อผู้ใช้"
        autoComplete="username"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />
      <input
        type="password"
        placeholder="รหัสผ่าน"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {error && <div className="banner error">{error}</div>}
      <div className="submit" style={{ position: "static", padding: 0, marginTop: 12 }}>
        <button type="submit" disabled={busy || !username || !password}>
          {busy ? "กำลังเข้าใช้งาน…" : "เข้าใช้งาน"}
        </button>
      </div>
    </form>
  );
}

export default function App() {
  const [token, setToken] = useState(getToken());

  if (!token) {
    return <Login onDone={() => setToken(getToken())} />;
  }
  return (
    <ShopFloor
      key={getUsername()}
      onLogout={() => {
        clearToken();
        setToken(null);
      }}
    />
  );
}
