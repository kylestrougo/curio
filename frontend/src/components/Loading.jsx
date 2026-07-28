export default function Loading({ children, style }) {
  return (
    <div className="loading" style={style}>
      <span className="dots">
        <i />
        <i />
        <i />
      </span>{' '}
      {children}
    </div>
  );
}
