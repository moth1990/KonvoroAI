import { Navigate, Route, Routes } from "react-router";

import { useMe } from "./api/QueryProvider";
import { AuthBridge, RequireAuth } from "./auth/auth";
import { HomeScreen } from "./screens/Home";
import { LoginScreen } from "./screens/Login";
import { NewQuoteScreen } from "./screens/newQuote/NewQuote";
import { Placeholder } from "./screens/Placeholder";

/** `/build` exists only when `chat_quote_builder` is on: off, it behaves like any unknown path (13 §3.2). */
function BuildRoute() {
  const me = useMe();
  if (!me.data) return null;
  return me.data.flags.chat_quote_builder ? <Placeholder screen="build" /> : <Navigate to="/home" replace />;
}

/** The prototype's routes (`ROUTES`, line 647) as paths. Unknown paths go home, like its `route()`. */
export default function App() {
  return (
    <>
      <AuthBridge />
      <Routes>
        <Route path="/login" element={<LoginScreen />} />
        <Route element={<RequireAuth />}>
          <Route path="/home" element={<HomeScreen />} />
          <Route path="/new" element={<NewQuoteScreen />} />
          <Route path="/review/:quoteId?" element={<Placeholder screen="review" />} />
          <Route path="/audit" element={<Placeholder screen="audit" />} />
          <Route path="/prices" element={<Placeholder screen="prices" />} />
          <Route path="/queue" element={<Placeholder screen="queue" />} />
          <Route path="/prefs" element={<Placeholder screen="prefs" />} />
          <Route path="/build" element={<BuildRoute />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Route>
      </Routes>
    </>
  );
}
