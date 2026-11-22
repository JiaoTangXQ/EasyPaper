/** A looping, decorative demonstration of how a paper is read in EasyPaper. */
export default function ReadingDemo() {
  return (
    <figure className="reading-demo" aria-label="阅读方式示例：原文高亮、对照译文和点读释义">
      <div className="reading-demo-chrome" aria-hidden="true">
        <span>Section 3 · Method</span>
        <span className="segmented">
          <span className="segmented-option" aria-pressed="false">
            原文
          </span>
          <span className="segmented-option" aria-pressed="true" style={{ background: "#fff", borderRadius: 8 }}>
            对照
          </span>
        </span>
      </div>
      <p className="reading-demo-en" lang="en">
        We <span className="demo-word">reuse</span> temporary buffers, <mark>which cuts peak memory by 30%</mark>{" "}
        without slowing training.
      </p>
      <p className="reading-demo-zh">
        我们复用临时缓冲区，<mark>使峰值内存降低 30%</mark>，且不拖慢训练。
      </p>
      <div className="reading-demo-gloss" aria-hidden="true">
        <span>单词 · 点读</span>
        <strong lang="en">reuse</strong>
        <span>v. 复用，重复使用</span>
      </div>
    </figure>
  );
}
