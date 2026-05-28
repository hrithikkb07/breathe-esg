import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Leaf } from "lucide-react";
import { Button } from "../components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(form.username, form.password);
      navigate("/");
    } catch {
      setError("Invalid credentials. Try analyst / demo1234");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center gap-3 mb-10">
          <div className="w-9 h-9 bg-teal-500 rounded-lg flex items-center justify-center">
            <Leaf className="w-5 h-5 text-slate-900" strokeWidth={2.5} />
          </div>
          <div>
            <p className="text-base font-semibold text-slate-100">Breathe ESG</p>
            <p className="text-xs text-slate-500">Data Ingestion Platform</p>
          </div>
        </div>

        <div className="bg-surface-raised border border-surface-border rounded-xl p-8">
          <h1 className="text-lg font-semibold text-slate-100 mb-1">Sign in</h1>
          <p className="text-sm text-slate-500 mb-6">Analyst access — Acme Corporation</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Username</label>
              <input
                type="text"
                autoComplete="username"
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                className="w-full bg-surface-muted border border-surface-border text-slate-200 text-sm rounded-md px-3 py-2.5 focus:outline-none focus:ring-1 focus:ring-teal-500 placeholder:text-slate-600"
                placeholder="analyst"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Password</label>
              <input
                type="password"
                autoComplete="current-password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="w-full bg-surface-muted border border-surface-border text-slate-200 text-sm rounded-md px-3 py-2.5 focus:outline-none focus:ring-1 focus:ring-teal-500 placeholder:text-slate-600"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-800 rounded-md px-3 py-2">
                {error}
              </p>
            )}

            <Button type="submit" loading={loading} className="w-full justify-center">
              Sign in
            </Button>
          </form>

          <div className="mt-6 pt-5 border-t border-surface-border">
            <p className="text-xs text-slate-600 font-medium mb-2">Demo credentials</p>
            <div className="space-y-1 font-mono text-xs text-slate-500">
              <p><span className="text-slate-400">analyst</span> / demo1234</p>
              <p><span className="text-slate-400">admin</span> / admin1234</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
