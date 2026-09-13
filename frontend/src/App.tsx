import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Reader from "./pages/Reader";
import KnowledgeBase from "./pages/KnowledgeBase";
import PaperDetail from "./pages/PaperDetail";
import FlashcardReview from "./pages/FlashcardReview";
import KnowledgeGraph from "./pages/KnowledgeGraph";
import PaperSummary from "./pages/PaperSummary";
import Layout from "./components/Layout";
import Settings from "./pages/Settings";

const PrivateRoute = ({ children }: { children: JSX.Element }) => {
  const token = localStorage.getItem("token");
  return token ? children : <Navigate to="/login" />;
};

function App() {
  return (
    <Router>
      <Toaster richColors position="top-center" />
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
          <Route path="/knowledge/review" element={<FlashcardReview />} />
          <Route path="/knowledge/graph" element={<KnowledgeGraph />} />
        </Route>

        <Route path="/" element={<Navigate to="/dashboard" />} />
      </Routes>
    </Router>
  );
}

export default App;
