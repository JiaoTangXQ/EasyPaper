/** EasyPaper: a curled paper e, a red ink dot, and a handwritten wordmark. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect x="0.5" y="0.5" width="63" height="63" rx="17" fill="#191817" stroke="#393735" />
      <path fill="#fff" fillRule="evenodd" d="M51 43C47 50 39 54 30 54C17 54 10 46 10 35C10 26 15 20 22 17C17 16 15 13 16 9C17 7 19 5 20 5C18 10 23 11 29 11H35C47 11 55 17 55 27C55 35 49 39 40 39H22C24 45 28 47 34 47C40 47 45 43 47 39Z M22 30H39C43 30 45 28 45 25C45 20 40 18 35 18C29 18 24 23 22 30Z" />
      <circle cx="52" cy="51" r="2.5" fill="#bd392b" />
    </svg>
  );
}

export default function Brand() {
  return (
    <span className="brand-lockup" role="img" aria-label="EasyPaper">
      <BrandMark />
      <img className="brand-wordmark" src="/brand/wordmark.svg" alt="" aria-hidden="true" width="138" height="31" />
    </span>
  );
}
