export default function AskBox({
  value,
  onChange,
  onSubmit,
  placeholder,
  action = 'Go',
  disabled = false,
  style,
}) {
  return (
    <div className="ask" style={style}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
        placeholder={placeholder}
      />
      <button onClick={onSubmit} disabled={disabled || !value.trim()}>
        {action}
      </button>
    </div>
  );
}
