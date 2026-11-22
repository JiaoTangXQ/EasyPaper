import { NavLink } from "react-router-dom";
import { BookA, Network, NotebookPen } from "lucide-react";

/** The three ways to browse what you have kept: by paper, by concept, by term. */
export default function KnowledgeNav() {
  return (
    <nav className="subnav" aria-label="知识浏览方式">
      <NavLink end to="/knowledge">
        <NotebookPen aria-hidden="true" />
        论文笔记
      </NavLink>
      <NavLink to="/knowledge/graph">
        <Network aria-hidden="true" />
        概念图谱
      </NavLink>
      <NavLink to="/knowledge/terms">
        <BookA aria-hidden="true" />
        术语本
      </NavLink>
    </nav>
  );
}
