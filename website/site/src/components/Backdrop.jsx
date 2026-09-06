// Fixed page backdrop: three slow signal rings pushing outward, plus the
// warm/cool wash defined in global.css. Pure decoration.
export default function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <svg viewBox="0 0 600 600" preserveAspectRatio="xMidYMid slice">
        <g>
          <circle className="backdrop-ring" cx="300" cy="300" r="290" />
          <circle className="backdrop-ring" cx="300" cy="300" r="290" />
          <circle className="backdrop-ring" cx="300" cy="300" r="290" />
        </g>
      </svg>
    </div>
  )
}
