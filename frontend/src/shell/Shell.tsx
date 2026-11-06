import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";

import { logout } from "../api/client";
import { useHomeSummary, useMe } from "../api/QueryProvider";
import { Icon, Logo, type IconName } from "../ui/Icon";
import { quotaView } from "./quota";

interface NavItem {
  to: string;
  /** Other paths this item stands for: the chat builder is a new quote too (prototype `shell("new")`, line 1335). */
  also?: string[];
  label: string;
  icon: IconName;
  count?: number;
}

/** The prototype's `navItems()` (line 690), in the same order. */
export function navItems(queuePending: number): NavItem[] {
  return [
    { to: "/home", label: "בית", icon: "home" },
    { to: "/new", also: ["/build"], label: "הצעה חדשה", icon: "plus" },
    { to: "/audit", label: "בדיקת הצעה", icon: "audit" },
    { to: "/prices", label: "מחירון", icon: "tag" },
    { to: "/queue", label: "תור אישור", icon: "queue", count: queuePending || undefined },
    { to: "/prefs", label: "הגדרות", icon: "gear" },
  ];
}

/** NavLink marks its own path as the page; `on`: one of the item's other paths is open, so it is marked too. */
function NavItemLink({
  to,
  on,
  children,
  ...rest
}: {
  to: string;
  on: boolean;
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
}) {
  if (on)
    return (
      <Link to={to} aria-current="page" {...rest}>
        {children}
      </Link>
    );
  return (
    <NavLink to={to} {...rest}>
      {children}
    </NavLink>
  );
}

/**
 * The app frame (prototype `shell()`, lines 691–714): the rail on desktop, the tab bar under 860px,
 * the quota banner (01 §4.5) and the page's top bar.
 */
export function Shell({ title, bare = false, children }: { title?: string; bare?: boolean; children: ReactNode }) {
  const me = useMe();
  const summary = useHomeSummary();
  const signOut = useSignOut();
  const quota = me.data ? quotaView(me.data.quota) : null;
  const nav = navItems(summary.data?.queue_pending ?? 0);
  const { pathname } = useLocation();
  const also = (item: NavItem) => !!item.also?.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  return (
    <div className="shell">
      <aside className="rail" aria-label="ניווט">
        <Logo />
        {nav.map((item) => (
          // NavLink sets aria-current="page" on the active item, which the prototype's CSS styles.
          <NavItemLink key={item.to} to={item.to} on={also(item)} className="nav-a">
            <Icon name={item.icon} />
            <span>{item.label}</span>
            {item.count ? (
              <span className="count" aria-label={`${item.count} ממתינים`}>
                {item.count}
              </span>
            ) : null}
          </NavItemLink>
        ))}
        <div className="rail-foot">
          <div className="small" data-testid="quota-meter">
            <div className="eyebrow">הצעות החודש</div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="num">{quota?.label ?? "—"}</span>
              <span className="muted">{me.data?.plan.name_he}</span>
            </div>
            {quota?.pct != null && (
              <div
                className={`meter${quota.tone === "ok" ? "" : " warn"}`}
                style={{ marginTop: 6 }}
                role="meter"
                aria-label="הצעות החודש"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={quota.pct}
              >
                <i style={{ width: `${quota.pct}%` }} />
              </div>
            )}
          </div>
          <div className="row small">
            <span
              className="muted"
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                direction: "ltr",
                textAlign: "right", // at the start of the RTL row, like the prototype
                flex: 1,
                minWidth: 0,
              }}
              title={me.data?.user.email}
            >
              {me.data?.user.email}
            </span>
            <span className="spacer" />
            <button
              className="btn ghost sm"
              type="button"
              data-testid="logout"
              title="יציאה"
              aria-label="יציאה"
              onClick={signOut}
            >
              <Icon name="out" />
            </button>
          </div>
        </div>
      </aside>
      <div className="main" id="main">
        {quota?.banner && (
          <div
            className={`quota-banner${quota.blocked ? " full" : ""}`}
            id="quota-banner"
            role="status"
            data-testid="quota-banner"
          >
            {quota.banner}
          </div>
        )}
        {title !== undefined && (
          <header className="topbar">
            {title ? <h1>{title}</h1> : null}
            <span className="spacer" />
          </header>
        )}
        {/* bare: the screen fills the main area itself (prototype `shell(…, {bare:true})`, the review screen) */}
        {bare ? children : <div className="content">{children}</div>}
      </div>
      <nav className="tabbar" aria-label="ניווט">
        {nav.map((item) => (
          <NavItemLink key={item.to} to={item.to} on={also(item)} aria-label={item.label}>
            <Icon name={item.icon} />
            <span aria-hidden="true">{item.label.split(" ")[0]}</span>
            {item.count ? (
              <span className="count" aria-hidden="true">
                {item.count}
              </span>
            ) : null}
          </NavItemLink>
        ))}
      </nav>
    </div>
  );
}

/** The prototype puts logout in the rail (hidden under 860px) and in settings (S24). Until S24 the settings
 * placeholder offers it too, so mobile users can sign out. */
export function useSignOut() {
  const queries = useQueryClient();
  const navigate = useNavigate();
  return async () => {
    await logout();
    queries.clear();
    navigate("/login", { replace: true });
  };
}
