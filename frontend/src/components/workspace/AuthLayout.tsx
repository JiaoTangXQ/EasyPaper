import type { ReactNode } from "react";
import Brand from "@/components/Brand";
import ReadingDemo from "./ReadingDemo";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth-layout">
      <section className="auth-intro ep-enter">
        <Brand />
        <h1>
          读懂论文，
          <br />
          <span>把理解留在原文旁边。</span>
        </h1>
        <p>完整阅读、多版本对照、点词即查、就地提问。读过的内容，可以整理、复习和导出。</p>
        <ReadingDemo />
      </section>
      <section className="auth-form">{children}</section>
    </main>
  );
}
