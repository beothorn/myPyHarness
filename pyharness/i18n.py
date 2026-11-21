"""User-facing strings for the Python side, in English (en) and Brazilian Portuguese (pt_br).

The web page has its own copy of the page strings (ui.html). Tool *results* sent to the model stay in English.
"""
LANGS = ("en", "pt_br")
DEFAULT = "en"

M = {
    "en": {
        # auth
        "auth.open_url": "Open this URL to sign in with your ChatGPT account:\n{url}",
        "auth.logged_in": "Logged in {who}",
        "auth.done_page": "myPyHarness: login complete. You can close this tab.",
        "auth.timeout": "Login timed out.",
        "auth.failed": "Login failed: {err}",
        "auth.no_code": "no code returned",
        "auth.not_logged": "Not logged in. Run login first.",
        "auth.port": "Cannot listen on port {port} (is the Codex CLI login running?): {err}",
        "auth.http": "HTTP {code} from auth server: {body}",
        "auth.unreachable": "Cannot reach auth server: {reason}",
        # agent
        "agent.no_model": "no model selected",
        "agent.max_steps": "Stopped after {n} steps.",
        "agent.stopped": "Stopped.",
        "agent.denied": "denied by the user",
        "agent.model_hint": " — pick another model from the list in the header.",
        # approval prompts
        "p.write": "WRITE {path} ({n} chars)",
        "p.edit": "EDIT {path}\n--- before\n{old}\n+++ after\n{new}",
        "p.fetch": "FETCH URL {url}",
        "p.read_outside": "READ outside the working folder:\n{what}",
        "p.resolved": "Resolved location(s):\n{paths}",
        "cmd.title": "RUN COMMAND (not sandboxed: runs on your computer with your permissions)",
        "cmd.what": "What it does (the model's explanation):",
        "cmd.no_expl": "(no explanation)",
        "cmd.command": "Command:",
        "cmd.folder": "Folder: {cwd}  ·  max time: {t}s",
        "cmd.warn": "⚠ The explanation was written by the model; check the command itself before allowing.",
        "banner.read": "The agent wants to read content, make sure it is not sensitive content",
        "banner.write": "The agent wants to change content outside the working folder, make sure you trust this",
        "banner.command": "This command seems to touch content outside the working folder, make sure it is not sensitive",
        # server
        "srv.save_failed": "Could not save the session: {err}",
        "srv.busy": "the agent is busy; stop it first",
        "srv.login_first": "sign in first",
        "srv.pick_dir": "choose a directory first",
        "srv.go_config": "go back to the configuration to change the folder",
        "srv.not_folder": "not a folder",
        "srv.not_root": "pick a folder, not a disk root",
        "srv.no_session": "no active session",
        "srv.model_na": "model not available for this account",
        "srv.open_failed": "could not open the session: {err}",
        "srv.folder_gone": "this session's folder no longer exists",
        "srv.login_ok": "Login successful.",
        "srv.login_fail": "Login failed: {err}",
        "srv.console": "Sessions saved in: {sessions}\nUI: {url}\nCtrl+C to quit.",
        "srv.create_agents": "Create AGENTS.md",
        "agents.interview": (
            "This directory has no AGENTS.md yet and I want to create one.\n"
            "1) Quickly explore the project (list_dir, README, manifest files such as package.json, pyproject.toml, "
            "requirements.txt, Makefile, etc.) to find out what you can on your own.\n"
            "2) Then ask me a few questions (at most 6, numbered and short) only about what you could not find out: "
            "project goal, stack and versions, how to run/test/build, code conventions and style, what you must NEVER "
            "do in this project, and workflow preferences. Stop and wait for my answers.\n"
            "3) When you have enough information, write AGENTS.md in the project root with write_file (short, "
            "objective sections, in the language I write in) and tell me in one sentence what you wrote."),
        # usage status
        "st.title": "📊 Usage status",
        "st.account": "account {who}",
        "st.plan": "plan {plan}",
        "st.model": "Model: {model} · level: {effort}",
        "st.none": "(none)",
        "st.error": "Could not get account usage: {err}",
        "st.window": "• {label}: {used}% used · {left}% available",
        "st.renews": " · renews {when}",
        "st.unknown": "Unknown response format:",
        "st.tokens": "Session tokens: {i} in · {o} out",
        "w.generic": "Window",
        "w.5h": "5-hour window",
        "w.week": "Weekly window",
        "w.hours": "{h} h window",
        "w.mins": "{m} min window",
        "t.now": "now",
        "t.in": "in {parts}",
        # CLI
        "cli.login_start": "Not logged in; starting login.",
        "cli.approval": "\n--- approval needed ---",
        "cli.warning": "[WARNING] ",
        "cli.allow": "Allow? [y/N] ",
        "cli.models": "Available models: {list}",
        "cli.no_models": "Could not get the model list ({err}). Use --model NAME.",
        "cli.start": "Project folder: {root}\nModel: {model}. Commands: /reset, /quit",
        "cli.prompt": "\nyou> ",
        "cli.logged_out": "Logged out.",
        "cli.not_dir": "Not a folder: {root}",
        "cli.auth_error": "Auth error: {err}",
        # prompt prefix for the model
        "model.language": ("LANGUAGE: always reply to the user in English, including text inside HTML widgets, and write "
                           "files you create for the user (such as AGENTS.md) in English unless asked otherwise."),
    },
    "pt_br": {
        "auth.open_url": "Abra este endereço para entrar com sua conta ChatGPT:\n{url}",
        "auth.logged_in": "Login realizado: {who}",
        "auth.done_page": "myPyHarness: login concluído. Você pode fechar esta aba.",
        "auth.timeout": "Tempo esgotado no login.",
        "auth.failed": "Falha no login: {err}",
        "auth.no_code": "nenhum código retornado",
        "auth.not_logged": "Não está logado. Faça o login primeiro.",
        "auth.port": "Não foi possível escutar a porta {port} (o login do Codex CLI está aberto?): {err}",
        "auth.http": "HTTP {code} do servidor de autenticação: {body}",
        "auth.unreachable": "Não foi possível acessar o servidor de autenticação: {reason}",
        "agent.no_model": "nenhum modelo selecionado",
        "agent.max_steps": "Parado após {n} passos.",
        "agent.stopped": "Interrompido.",
        "agent.denied": "negado pelo usuário",
        "agent.model_hint": " — escolha outro modelo na lista do cabeçalho.",
        "p.write": "GRAVAR {path} ({n} caracteres)",
        "p.edit": "EDITAR {path}\n--- antes\n{old}\n+++ depois\n{new}",
        "p.fetch": "ACESSAR URL {url}",
        "p.read_outside": "LER fora da pasta de trabalho:\n{what}",
        "p.resolved": "Local(is) resolvido(s):\n{paths}",
        "cmd.title": "EXECUTAR COMANDO (sem sandbox: roda no seu computador com as suas permissões)",
        "cmd.what": "O que faz (explicação do modelo):",
        "cmd.no_expl": "(sem explicação)",
        "cmd.command": "Comando:",
        "cmd.folder": "Pasta: {cwd}  ·  tempo máximo: {t}s",
        "cmd.warn": "⚠ A explicação foi escrita pelo modelo; confira o comando em si antes de permitir.",
        "banner.read": "O agente quer ler conteúdo, certifique-se de que não é conteúdo sensível",
        "banner.write": "O agente quer alterar conteúdo fora da pasta de trabalho, certifique-se de que você confia nisso",
        "banner.command": "Este comando parece acessar conteúdo fora da pasta de trabalho, certifique-se de que não é conteúdo sensível",
        "srv.save_failed": "Não foi possível salvar a sessão: {err}",
        "srv.busy": "o agente está ocupado; pare-o antes",
        "srv.login_first": "faça login primeiro",
        "srv.pick_dir": "escolha um diretório primeiro",
        "srv.go_config": "volte à configuração para trocar a pasta",
        "srv.not_folder": "não é uma pasta",
        "srv.not_root": "escolha uma pasta, não a raiz do disco",
        "srv.no_session": "nenhuma sessão ativa",
        "srv.model_na": "modelo indisponível para esta conta",
        "srv.open_failed": "não foi possível abrir a sessão: {err}",
        "srv.folder_gone": "a pasta desta sessão não existe mais",
        "srv.login_ok": "Login realizado com sucesso.",
        "srv.login_fail": "Falha no login: {err}",
        "srv.console": "Sessões salvas em: {sessions}\nInterface: {url}\nCtrl+C para sair.",
        "srv.create_agents": "Criar AGENTS.md",
        "agents.interview": (
            "Este diretório ainda não tem um AGENTS.md e eu quero criar um.\n"
            "1) Explore rapidamente o projeto (list_dir, README, arquivos de manifesto como package.json, "
            "pyproject.toml, requirements.txt, Makefile etc.) para descobrir o que for possível sozinho.\n"
            "2) Depois me faça poucas perguntas (no máximo 6, numeradas e curtas) só sobre o que você não conseguiu "
            "descobrir: objetivo do projeto, stack e versões, como rodar/testar/gerar build, convenções de código e "
            "estilo, o que você NUNCA deve fazer neste projeto, e preferências de fluxo de trabalho. Pare e espere "
            "minhas respostas.\n"
            "3) Quando tiver informação suficiente, grave o AGENTS.md na raiz com write_file (seções curtas e "
            "objetivas, no idioma em que eu escrever) e diga em uma frase o que gravou."),
        "st.title": "📊 Status de uso",
        "st.account": "conta {who}",
        "st.plan": "plano {plan}",
        "st.model": "Modelo: {model} · nível: {effort}",
        "st.none": "(nenhum)",
        "st.error": "Não foi possível obter o uso da conta: {err}",
        "st.window": "• {label}: {used}% usado · {left}% disponível",
        "st.renews": " · renova {when}",
        "st.unknown": "Formato de resposta desconhecido:",
        "st.tokens": "Tokens nesta sessão: {i} entrada · {o} saída",
        "w.generic": "Janela",
        "w.5h": "Janela de 5 horas",
        "w.week": "Janela semanal",
        "w.hours": "Janela de {h} h",
        "w.mins": "Janela de {m} min",
        "t.now": "agora",
        "t.in": "em {parts}",
        "cli.login_start": "Não está logado; iniciando login.",
        "cli.approval": "\n--- aprovação necessária ---",
        "cli.warning": "[ATENÇÃO] ",
        "cli.allow": "Permitir? [s/N] ",
        "cli.models": "Modelos disponíveis: {list}",
        "cli.no_models": "Não foi possível obter a lista de modelos ({err}). Use --model NOME.",
        "cli.start": "Pasta do projeto: {root}\nModelo: {model}. Comandos: /reset, /quit",
        "cli.prompt": "\nvocê> ",
        "cli.logged_out": "Sessão encerrada.",
        "cli.not_dir": "Não é uma pasta: {root}",
        "cli.auth_error": "Erro de autenticação: {err}",
        "model.language": ("LANGUAGE: always reply to the user in Brazilian Portuguese (português do Brasil), including "
                           "text inside HTML widgets, and write files you create for the user (such as AGENTS.md) in "
                           "Brazilian Portuguese unless asked otherwise."),
    },
}


def norm(lang):
    return lang if lang in LANGS else DEFAULT


def t(lang, key, **kw):
    s = M.get(norm(lang), M[DEFAULT]).get(key) or M[DEFAULT][key]
    return s.format(**kw) if kw else s
