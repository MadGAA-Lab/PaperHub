import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/sonner";
import { ChatPage } from "@/pages/ChatPage";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <ChatPage />
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
