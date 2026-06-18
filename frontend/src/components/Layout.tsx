import { Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { LogOut, User as UserIcon, FileText, Brain } from "lucide-react";

const Layout = () => {
    const navigate = useNavigate();
    const userEmail = localStorage.getItem("email") || "用户";

    const handleLogout = () => {
        localStorage.removeItem("token");
        localStorage.removeItem("email");
        navigate("/login");
    };

    return (
        <div className="min-h-screen bg-gray-50 font-sans text-gray-900">
            {/* Header */}
            <header className="sticky top-0 z-50 w-full border-b bg-white/80 backdrop-blur-md supports-[backdrop-filter]:bg-white/60">
                <div className="container mx-auto flex h-16 items-center justify-between px-4">
                    <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate("/dashboard")}>
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                            <FileText className="h-5 w-5" />
                        </div>
                        <span className="text-lg font-semibold tracking-tight">EasyPaper</span>
                    </div>

                    <div className="flex items-center gap-4">
                        <Button
                            variant="ghost"
                            size="sm"
                            className="gap-2 text-muted-foreground hover:text-primary"
                            onClick={() => navigate("/knowledge")}
                        >
                            <Brain className="h-4 w-4" />
                            <span className="hidden sm:inline">知识库</span>
                        </Button>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="ghost" className="relative h-9 w-9 rounded-full">
                                    <Avatar className="h-9 w-9">
                                        <AvatarImage src="/avatars/01.png" alt="@user" />
                                        <AvatarFallback className="bg-primary/10 text-primary">
                                            <UserIcon className="h-4 w-4" />
                                        </AvatarFallback>
                                    </Avatar>
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent className="w-56" align="end" forceMount>
                                <DropdownMenuLabel className="font-normal">
                                    <div className="flex flex-col space-y-1">
                                        <p className="text-sm font-medium leading-none">我的账户</p>
                                        <p className="text-xs leading-none text-muted-foreground">
                                            {userEmail}
                                        </p>
                                    </div>
                                </DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onClick={handleLogout} className="text-red-600 focus:text-red-600">
                                    <LogOut className="mr-2 h-4 w-4" />
                                    <span>退出登录</span>
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="container mx-auto py-6 px-4">
                <Outlet />
            </main>
        </div>
    );
};

export default Layout;
