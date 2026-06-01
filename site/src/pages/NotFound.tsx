import { Link } from "react-router-dom";
import { Empty } from "@/components/ui";

export function NotFound() {
  return (
    <Empty>
      <div className="text-4xl font-bold text-fg">404</div>
      <p>That page isn't in the dex.</p>
      <Link to="/" className="btn btn-accent mt-2">
        Back to overview
      </Link>
    </Empty>
  );
}
