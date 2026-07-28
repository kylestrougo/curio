export const KIND_WORD = { fact: 'Fact', question: 'Question', topic: 'Path' };

export default function Door({ label, type = 'topic', kindLabel, onClick, wild = false, style }) {
  return (
    <button className={'door ' + (wild ? 'wild' : type)} onClick={onClick} style={style}>
      <span className="kind">{kindLabel || KIND_WORD[type] || 'Path'}</span>
      <span className="lbl">{label}</span>
    </button>
  );
}
