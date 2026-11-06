import { Navigate, Outlet, Route, Routes, useLocation } from "react-router";

import { useMe } from "./api/QueryProvider";
import { AuthBridge, RequireAuth } from "./auth/auth";
import { AuditScreen } from "./screens/audit/Audit";
import { BuildScreen } from "./screens/build/Build";
import { NewAuditScreen } from "./screens/audit/NewAudit";
import { HomeScreen } from "./screens/Home";
import { LoginScreen } from "./screens/Login";
import { NewQuoteScreen } from "./screens/newQuote/NewQuote";
import { Placeholder } from "./screens/Placeholder";
import { PrefsScreen } from "./screens/prefs/Prefs";
import { PricesScreen } from "./screens/prices/Prices";
import { QueueScreen } from "./screens/queue/Queue";
import { ReviewScreen } from "./screens/review/Review";
import { WelcomeScreen } from "./screens/welcome/Welcome";

/** `/build` exists only when `chat_quote_builder` is on: off, it behaves like any unknown path (13 §3.2). */
function BuildRoute() {
  const me = useMe();
  if (!me.data) return null;
  return me.data.flags.chat_quote_builder ? <BuildScreen /> : <Navigate to="/home" replace />;
}

/** The audit (S16) is behind `quote_audit`, evaluated on the server (13 §3); off, `/audit` stays a placeholder. */
function AuditRoute({ results = false }: { results?: boolean }) {
  const me = useMe();
  if (!me.data) return null;
  if (!me.data.flags.quote_audit) return <Placeholder screen="audit" />;
  return results ? <AuditScreen /> : <NewAuditScreen />;
}

/** The settings screen (S24) is behind `settings_screen`; off, a placeholder with the sign-out button. */
function PrefsRoute() {
  const me = useMe();
  if (!me.data) return null;
  return me.data.flags.settings_screen ? <PrefsScreen /> : <Placeholder screen="prefs" />;
}

/** The approval queue (S24, 00 §14.2) is behind `approval_queue`, like its API. */
function QueueRoute() {
  const me = useMe();
  if (!me.data) return null;
  return me.data.flags.approval_queue ? <QueueScreen /> : <Placeholder screen="queue" />;
}

/** A new factory answers two questions and accepts the data terms first (10 §5.1, S24 decision 1): until then every
 * page sends it to /welcome. The server decides (`onboarding_required`: the `onboarding` flag and the terms). */
function OnboardingGate() {
  const me = useMe();
  const location = useLocation();
  if (me.data?.onboarding_required && location.pathname !== "/welcome") return <Navigate to="/welcome" replace />;
  return <Outlet />;
}

function WelcomeRoute() {
  const me = useMe();
  if (!me.data) return null;
  return <WelcomeScreen answered={!me.data.onboarding_required} />;
}

/** The prototype's routes (`ROUTES`, line 647) as paths. Unknown paths go home, like its `route()`. */
export default function App() {
  return (
    <>
      <AuthBridge />
      <Routes>
        <Route path="/login" element={<LoginScreen />} />
        <Route element={<RequireAuth />}>
          <Route element={<OnboardingGate />}>
            <Route path="/welcome" element={<WelcomeRoute />} />
            <Route path="/home" element={<HomeScreen />} />
            <Route path="/new" element={<NewQuoteScreen />} />
            <Route path="/review/:quoteId?" element={<ReviewScreen />} />
            <Route path="/audit" element={<AuditRoute />} />
            <Route path="/audit/:auditId" element={<AuditRoute results />} />
            <Route path="/prices" element={<PricesScreen />} />
            <Route path="/queue" element={<QueueRoute />} />
            <Route path="/prefs" element={<PrefsRoute />} />
            <Route path="/build/:drawingId?" element={<BuildRoute />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Route>
        </Route>
      </Routes>
    </>
  );
}
