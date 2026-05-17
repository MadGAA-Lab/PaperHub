import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          ChatPage placeholder — Task 13 will render here.
        </div>
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
