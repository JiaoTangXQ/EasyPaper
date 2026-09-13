import type { ReactNode } from "react";
import Brand from "@/components/Brand";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth-layout">
      <section className="auth-intro">
        <div className="app-brand">
          <Brand />
        </div>
        <h1>
          读懂论文。
          <br />
          把理解留在原文旁边。
        </h1>
        <p>
          完整阅读、多版本对照、就地提问。
          <br />
          读过的内容，可以整理、复习和导出。
        </p>
        <div className="auth-reading-example">
          <span>阅读方式示例</span>
          <p lang="en">
            Read the paper. <mark>Keep your understanding alongside it.</mark>
          </p>
          <p>
            读完论文，<mark>把理解留在原文旁边。</mark>
          </p>
          <div>原文与译文对照 · 批注按内容匹配</div>
        </div>
      </section>
      <section className="auth-form">{children}</section>
    </main>
  );
}
