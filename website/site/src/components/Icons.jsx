// Small stroke icons (24x24, currentColor). Only the ones the pages use.
const P = (d) => (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    {d}
  </svg>
)

export const Clock = P(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>)
export const Download = P(<><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></>)
export const FileText = P(<><path d="M14 3v5h5" /><path d="M4 17V5a2 2 0 0 1 2-2h8.5L20 7.5V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2Z" /><path d="M9 13h6M9 17h4" /></>)
export const Lock = P(<><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>)
export const Check = P(<><path d="M9 12l2 2 4-4" /><circle cx="12" cy="12" r="9" /></>)
export const Alert = P(<><path d="M12 9v4M12 17h.01" /><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" /></>)
export const ArrowRight = P(<><path d="M5 12h14M13 6l6 6-6 6" /></>)
export const Bolt = P(<><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z" /></>)
export const Message = P(<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></>)
export const Shield = P(<><path d="M12 3 4 6.5V11c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6.5L12 3Z" /></>)
export const Layers = P(<><path d="M12 2 2 7l10 5 10-5-10-5Z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" /></>)
export const Cube = P(<><path d="M12 2 2 7l10 5 10-5-10-5Z" /><path d="M2 7v10l10 5 10-5V7" /><path d="M12 12v10" /></>)
export const Terminal = P(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></>)
export const Gear = P(<><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v3M12 18.5v3M4.4 4.4l2.1 2.1M17.5 17.5l2.1 2.1M2.5 12h3M18.5 12h3M4.4 19.6l2.1-2.1M17.5 6.5l2.1-2.1" /></>)
export const ClipboardCheck = P(<><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>)
export const Book = P(<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>)
export const Cart = P(<><circle cx="9" cy="21" r="1" /><circle cx="20" cy="21" r="1" /><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" /></>)
export const Search = P(<><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>)
export const Info = P(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>)
