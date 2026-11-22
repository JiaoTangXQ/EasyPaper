import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Reader from "./pages/Reader";
import KnowledgeBase from "./pages/KnowledgeBase";
import PaperDetail from "./pages/PaperDetail";
import Review from "./pages/Review";
import KnowledgeGraph from "./pages/KnowledgeGraph";
import PaperSummary from "./pages/PaperSummary";
import Layout from "./components/Layout";
import Settings from "./pages/Settings";
import TermMemory from "./pages/TermMemory";
import { ConfirmHost } from "./components/ui/confirm";

const PrivateRoute = ({ children }: { children: JSX.Element }) => {
  const token = localStorage.getItem("token");
  return token ? children : <Navigate to="/login" />;
};

/** Old bookmarks keep working after review and terms moved. */
function LegacyRedirect({ to }: { to: string }) {
  const { search } = useLocation();
  const [path, query] = to.split("?");
  const params = new URLSearchParams(search);
  new URLSearchParams(query).forEach((value, key) => params.set(key, value));
  const suffix = params.toString();
  return <Navigate to={`${path}${suffix ? `?${suffix}` : ""}`} replace />;
}

function App() {
  return (
    <Router>
      <Toaster position="top-center" offset={68} gap={8} />
      <ConfirmHost />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        {/* Protected Routes with Layout */}
        <Route
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        >
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/reader/:taskId" element={<Reader />} />
          <Route path="/summary/:taskId" element={<PaperSummary />} />
          <Route path="/knowledge" element={<KnowledgeBase />} />
          <Route path="/knowledge/paper/:paperId" element={<PaperDetail />} />
          <Route path="/knowledge/graph" element={<KnowledgeGraph />} />
          <Route path="/knowledge/terms" element={<TermMemory />} />
          <Route path="/review" element={<Review />} />
          <Route path="/knowledge/review" element={<LegacyRedirect to="/review" />} />
          <Route path="/terms" element={<LegacyRedirect to="/knowledge/terms" />} />
        </Route>

        <Route path="/" element={<Navigate to="/dashboard" />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
