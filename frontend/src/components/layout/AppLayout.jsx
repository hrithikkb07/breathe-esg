import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { useAuth } from "../../hooks/useAuth";
import {
  LayoutDashboard,
  Upload,
  FileSearch,
  AlertTriangle,
  ClipboardCheck,
  ScrollText,
  LogOut,
  Leaf,
} from "lucide-react";

const NAV = [
  { to: "/",          label: "Overview",       icon: LayoutDashboard, end: true },
  { to: "/upload",    label: "Upload Data",     icon: Upload },
  { to: "/records",   label: "All Records",     icon: FileSearch },
  { to: "/flagged",   label: "Flagged",         icon: AlertTriangle },
  { to: "/review",    label: "Review Queue",    icon: ClipboardCheck },
  { to: "/audit-log", label: "Audit Log",       icon: ScrollText },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="flex h-screen bg-surface text-slate-200 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 flex flex-col border-r border-surface-border bg-surface-raised">
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-surface-border">
          <div className="w-7 h-7 bg-teal-500 rounded-md flex items-center justify-center flex-shrink-0">
            <Leaf className="w-4 h-4 text-slate-900" strokeWidth={2.5} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-100 leading-none">Breathe ESG</p>
            <p className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-widest">Analyst</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-100",
                  isActive
                    ? "bg-teal-500/10 text-teal-400 font-medium"
                    : "text-slate-500 hover:text-slate-300 hover:bg-surface-muted"
                )
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div className="px-3 py-4 border-t border-surface-border">
          <div className="px-3 py-2 mb-1">
            <p className="text-xs font-medium text-slate-300">{user?.username}</p>
            <p className="text-[10px] text-slate-600 uppercase tracking-wider">{user?.role}</p>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm text-slate-600 hover:text-red-400 hover:bg-red-900/20 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
