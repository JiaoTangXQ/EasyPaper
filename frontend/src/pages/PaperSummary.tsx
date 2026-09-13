import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

/** Kept as a compatibility URL. The map now lives beside its evidence in Reader. */
export default function PaperSummary() {
  const { taskId = "" } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  useEffect(() => {
    navigate(`/reader/${taskId}?panel=summary`, { replace: true });
  }, [navigate, taskId]);
  return (
    <div className="reader-empty">
      <Loader2 className="spin" size={30} />
      <p>正在打开论文地图…</p>
    </div>
  );
}
