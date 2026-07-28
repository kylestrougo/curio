import React from 'react';
import Loading from '../components/Loading.jsx';

export default function Recap({ w }) {
  const { recap, setRecap, openPage, closeWander, keepWandering, startFresh } = w;
  const failed = recap && recap.failed;

  return (
    <div className="recap">
      <div className="ey">The wander, closed</div>
      {recap === 'loading' ? (
        <Loading>Reading back over your path…</Loading>
      ) : failed ? (
        <div className="errline">
          {recap.failed}
          <button onClick={closeWander}>Try again</button>
          <button onClick={keepWandering} style={{ marginLeft: 6 }}>
            Keep wandering
          </button>
        </div>
      ) : recap ? (
        <>
          <div className="recap-path">
            {recap.path.map((t, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span className="sep"> › </span>}
                <span>{t}</span>
              </React.Fragment>
            ))}
          </div>
          <p className="recap-synth">{recap.synthesis}</p>
          {recap.thread && (
            <div className="recap-thread">
              <span className="tlabel">A thread to carry</span>
              <button
                className="thread-q"
                onClick={() => {
                  setRecap(null);
                  openPage(recap.thread, 'question', true);
                }}
              >
                {recap.thread}
              </button>
            </div>
          )}
          <div className="recap-actions">
            <button className="save" onClick={keepWandering}>
              Keep wandering
            </button>
            <button className="save" onClick={startFresh}>
              Start fresh
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
