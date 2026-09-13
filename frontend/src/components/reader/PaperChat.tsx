import { BrandMark } from "@/components/Brand";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowUp, Loader2, RotateCcw, X } from "lucide-react";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import "./paper-chat.css";

type Answer = {
  answer: string;
  reasoning?: string;
  uncertainty?: string;
  evidence_refs?: { page: number; quote: string }[];
};
type Turn = {
  id: string;
  question: string;
  selection: string;
  status: "pending" | "complete" | "error";
  answer?: Answer;
  error?: string;
};
type Props = {
  taskId: string;
  title: string;
  selection: string;
  clearSelection: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSource: (page: number) => void;
  portalContainer?: HTMLElement | null;
};

export default function PaperChat({
  taskId,
  title,
  selection,
  clearSelection,
  open,
  onOpenChange,
  onSource,
  portalContainer,
}: Props) {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [viewport, setViewport] = useState({ height: window.innerHeight, bottom: 0, mobile: window.innerWidth <= 700 });
  const composer = useRef<HTMLTextAreaElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  const followLatest = useRef(true);
  const scrollPosition = useRef(0);
  const asking = turns.some((turn) => turn.status === "pending");
  const compactPosition = viewport.mobile || viewport.height < 440;
  const shortViewport = viewport.height < 300;

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (!open) return;
    const visible = window.visualViewport;
    const update = () =>
      setViewport({
        height: visible?.height ?? window.innerHeight,
        bottom: visible ? Math.max(0, window.innerHeight - visible.height - visible.offsetTop) : 0,
        mobile: window.innerWidth <= 700,
      });
    update();
    window.addEventListener("resize", update);
    visible?.addEventListener("resize", update);
    visible?.addEventListener("scroll", update);
    return () => {
      window.removeEventListener("resize", update);
      visible?.removeEventListener("resize", update);
      visible?.removeEventListener("scroll", update);
    };
  }, [open]);
  useLayoutEffect(() => {
    const list = messages.current;
    if (open && list) list.scrollTop = followLatest.current ? list.scrollHeight : scrollPosition.current;
  }, [open, turns]);

  const answerTurn = async (turn: Turn, previous: Turn[]) => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const history = previous
      .filter((item) => item.status === "complete" && item.answer)
      .slice(-6)
      .flatMap((item) => [
        {
          role: "user",
          content: (item.selection ? `问题：${item.question}\n关注片段：${item.selection}` : item.question).slice(
            0,
            8000,
          ),
        },
        {
          role: "assistant",
          content: [item.answer!.answer, item.answer!.reasoning, item.answer!.uncertainty]
            .filter(Boolean)
            .join("\n")
            .slice(0, 8000),
        },
      ]);
    try {
      const { data } = await api.post<Answer>(
        `/api/reading/${taskId}/ask`,
        {
          question: turn.question,
          selection: turn.selection,
          history,
        },
        { signal: controller.signal },
      );
      if (!data.answer?.trim()) throw new Error("回答为空，请重试。");
      if (!controller.signal.aborted)
        setTurns((current) =>
          current.map((item) => (item.id === turn.id ? { ...item, status: "complete", answer: data } : item)),
        );
    } catch (error) {
      if (!controller.signal.aborted)
        setTurns((current) =>
          current.map((item) =>
            item.id === turn.id
              ? {
                  ...item,
                  status: "error",
                  error: getApiErrorMessage(error, "暂时未能获取回答，请重试。"),
                }
              : item,
          ),
        );
    } finally {
      if (request.current === controller) request.current = null;
    }
  };
  const send = () => {
    const question = draft.trim();
    if (!question || request.current) return;
    const turn: Turn = {
      id: crypto.randomUUID(),
      question,
      selection: selection.trim().slice(0, 8000),
      status: "pending",
    };
    followLatest.current = true;
    setTurns((current) => [...current, turn]);
    setDraft("");
    clearSelection();
    void answerTurn(turn, turns);
    composer.current?.focus();
  };
  const retry = (turn: Turn, index: number) => {
    if (request.current) return;
    setTurns((current) =>
      current.map((item) => (item.id === turn.id ? { ...item, status: "pending", error: undefined } : item)),
    );
    void answerTurn(turn, turns.slice(0, index));
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange} modal={viewport.mobile}>
      <Dialog.Trigger asChild>
        <button className="paper-chat-launcher" aria-label={open ? "收起论文对话" : "打开论文对话"} title="问这篇论文">
          {open ? <X size={22} /> : <BrandMark size={25} />}
          <span>问论文</span>
          {asking && !open && <Loader2 size={15} className="spin" aria-label="正在回答" />}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal container={portalContainer}>
        {viewport.mobile && <Dialog.Overlay className="paper-chat-overlay" />}
        <Dialog.Content
          className="paper-chat-window"
          data-short-viewport={shortViewport || undefined}
          style={{
            height: `min(600px, max(0px, calc(${viewport.height - (compactPosition ? 24 : 120)}px - env(safe-area-inset-bottom))))`,
            bottom: `calc(${compactPosition ? 12 : 88}px + env(safe-area-inset-bottom) + ${viewport.bottom}px)`,
          }}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            composer.current?.focus();
          }}
          onInteractOutside={(event) => {
            if (!viewport.mobile) event.preventDefault();
          }}
        >
          <header className="paper-chat-header">
            <BrandMark size={28} />
            <div>
              <Dialog.Title>EasyPaper 论文助手</Dialog.Title>
              <Dialog.Description title={title}>当前论文 · {title}</Dialog.Description>
            </div>
            <button
              type="button"
              className="paper-chat-icon"
              aria-label="开始新对话"
              title="开始新对话"
              disabled={asking || turns.length === 0}
              onClick={() => {
                setTurns([]);
                setDraft("");
                clearSelection();
                followLatest.current = true;
                composer.current?.focus();
              }}
            >
              <RotateCcw size={17} />
            </button>
            <Dialog.Close className="paper-chat-icon" aria-label="关闭论文对话">
              <X size={20} />
            </Dialog.Close>
          </header>
          <div
            className="paper-chat-messages"
            ref={messages}
            role="log"
            aria-label="本篇论文对话"
            aria-live="polite"
            onScroll={(event) => {
              const list = event.currentTarget;
              followLatest.current = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
              scrollPosition.current = list.scrollTop;
            }}
          >
            {turns.length === 0 ? (
              <div className="paper-chat-empty">
                <BrandMark size={36} />
                <h3>这篇论文，哪里想再读懂一点？</h3>
                <p>已关联当前论文，直接提问即可。</p>
                {["这篇论文解决了什么问题？", "这个方法有哪些局限？"].map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => {
                      setDraft(question);
                      composer.current?.focus();
                    }}
                  >
                    {question}
                  </button>
                ))}
              </div>
            ) : (
              turns.map((turn, index) => (
                <div className="paper-chat-turn" key={turn.id}>
                  <div className="paper-chat-question">
                    <span className="sr-only">你：</span>
                    {turn.selection && <blockquote>{turn.selection}</blockquote>}
                    <p>{turn.question}</p>
                  </div>
                  <div className="paper-chat-answer">
                    <span className="paper-chat-speaker">
                      <BrandMark size={17} />
                      EasyPaper
                    </span>
                    {turn.status === "pending" ? (
                      <p className="paper-chat-pending">
                        <Loader2 size={15} className="spin" />
                        正在结合论文回答…
                      </p>
                    ) : turn.status === "error" ? (
                      <div className="paper-chat-error" role="alert">
                        <p>{turn.error}</p>
                        <button disabled={asking} onClick={() => retry(turn, index)}>
                          重试回答
                        </button>
                      </div>
                    ) : turn.answer ? (
                      <>
                        <p>{turn.answer.answer}</p>
                        {turn.answer.reasoning && (
                          <details>
                            <summary>查看依据</summary>
                            <p>{turn.answer.reasoning}</p>
                          </details>
                        )}
                        {turn.answer.uncertainty && <p className="paper-chat-uncertainty">{turn.answer.uncertainty}</p>}
                        {!!turn.answer.evidence_refs?.length && (
                          <div className="paper-chat-sources" aria-label="原文来源">
                            {turn.answer.evidence_refs.map((source, sourceIndex) => (
                              <button key={sourceIndex} title={source.quote} onClick={() => onSource(source.page)}>
                                原文第 {source.page} 页
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>
          <form
            className="paper-chat-composer"
            onSubmit={(event) => {
              event.preventDefault();
              send();
            }}
          >
            {selection.trim() && (
              <div className="paper-chat-selection">
                <span title={selection}>引用选文：{selection}</span>
                <button type="button" className="paper-chat-icon" aria-label="移除引用选文" onClick={clearSelection}>
                  <X size={15} />
                </button>
              </div>
            )}
            <div className="paper-chat-input">
              <label className="sr-only" htmlFor="paper-chat-question">
                问题
              </label>
              <textarea
                ref={composer}
                id="paper-chat-question"
                value={draft}
                maxLength={4000}
                rows={shortViewport ? 1 : 2}
                placeholder="问问这篇论文…"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing &&
                    event.nativeEvent.keyCode !== 229
                  ) {
                    event.preventDefault();
                    send();
                  }
                }}
              />
              <button
                type="submit"
                className="paper-chat-send"
                aria-label="发送问题"
                disabled={asking || !draft.trim()}
              >
                <ArrowUp size={21} />
              </button>
            </div>
            <span className="paper-chat-hint">结合当前论文回答 · Shift + Enter 换行</span>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
