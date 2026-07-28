import Door from '../components/Door.jsx';
import AskBox from '../components/AskBox.jsx';
import Loading from '../components/Loading.jsx';

function BookmarkIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
      <path d="M6 3h12a1 1 0 0 1 1 1v16l-7-4-7 4V4a1 1 0 0 1 1-1z" />
    </svg>
  );
}

export default function Page({ w }) {
  const {
    current,
    loading,
    error,
    isSaved,
    toggleSave,
    tellMore,
    moreLoading,
    qaLoading,
    followQ,
    setFollowQ,
    askFollowUp,
    ask,
    setAsk,
    submitAsk,
    openPage,
    closeWander,
    visitedRef,
  } = w;

  return (
    <div className="page">
      {loading ? (
        <Loading>Opening the door…</Loading>
      ) : error ? (
        <div className="errline">
          {error.quota ? (
            error.message
          ) : (
            <>
              That door didn't open.
              <button onClick={() => openPage(error.label, error.type, error.resetTo, error.surprise)}>
                Try again
              </button>
            </>
          )}
        </div>
      ) : current ? (
        <>
          <h2>{current.title}</h2>
          <p className="blurb">{current.blurb}</p>
          {(current.more || []).map((m, i) => (
            <p className="blurb deeper" key={i}>
              {m}
            </p>
          ))}
          <div className="save-row">
            <button className={'save' + (isSaved ? ' on' : '')} onClick={toggleSave}>
              <BookmarkIcon filled={isSaved} />
              {isSaved ? 'Saved' : 'Save this page'}
            </button>
            <button className="save" onClick={tellMore} disabled={moreLoading}>
              {moreLoading ? 'Going deeper…' : 'Tell me more'}
            </button>
          </div>

          {((current.qa || []).length > 0 || qaLoading) && (
            <div className="qa-list">
              {(current.qa || []).map((x, i) => (
                <div className="qa" key={i}>
                  <p className="q">{x.q}</p>
                  <p className="a">{x.a}</p>
                </div>
              ))}
              {qaLoading && <Loading style={{ padding: '10px 2px' }}>Thinking it over…</Loading>}
            </div>
          )}
          <AskBox
            value={followQ}
            onChange={setFollowQ}
            onSubmit={askFollowUp}
            placeholder="Ask a follow-up about this…"
            action="Ask"
            disabled={qaLoading}
            style={{ marginBottom: 28 }}
          />

          <div className="next-label">Where to next?</div>
          <div className="doors">
            {(current.buttons || []).map((b, i) => (
              <Door key={i} label={b.label} type={b.type} onClick={() => openPage(b.label, b.type)} />
            ))}
          </div>
          <AskBox
            value={ask}
            onChange={setAsk}
            onSubmit={submitAsk}
            placeholder="…or steer it yourself"
            action="Go"
          />
          {visitedRef.current.length >= 3 ? (
            <div className="close-row">
              <button className="close-wander" onClick={closeWander}>
                ✦ Close the wander
              </button>
              <div className="foot" style={{ marginTop: 10 }}>
                Generated live
              </div>
            </div>
          ) : (
            <div className="foot">Generated live</div>
          )}
        </>
      ) : null}
    </div>
  );
}
