# myPyHarness (Português)

**Um *harness* de agente de IA simples: é só soltar numa pasta e usar.**
Python puro, só biblioteca padrão: nada para instalar, sem `pip`, sem executáveis.

🇬🇧 English: [README.md](README.md)

## Motivação

Alguns computadores não deixam instalar programas nem rodar executáveis, mas ainda permitem rodar Python. Nesses ambientes, a maioria das ferramentas de agente (CLIs, aplicativos desktop, Node/Electron) fica fora de questão.

O myPyHarness é o oposto: alguns arquivos Python que você copia para perto do seu projeto e inicia com `python harness.py`. Ele entra com a sua própria **conta ChatGPT** (o mesmo login do Codex CLI), então também não há chave de API para gerenciar.

## Recursos

- **Soltar e usar.** Copie a pasta, rode um comando. Só precisa de Python 3.8+.
- **Login com ChatGPT.** Um clique no navegador; os tokens ficam na sua pasta de usuário, nunca no projeto.
- **Trabalha dentro de uma pasta que você escolhe.** O agente lê e grava ali e em nenhum outro lugar.
- **Interface no navegador ou terminal.** Uma pequena página local (padrão) ou um chat simples com `--cli`.
- **Escolha de modelo e nível de raciocínio** a partir da lista que a sua conta realmente pode usar, e o botão **Status** mostra quanto dos limites do seu plano você já usou.
- **Respostas ricas.** O modelo responde em HTML e pode montar widgets interativos: blocos estilizados, botões, gráficos SVG, JavaScript. Eles rodam isolados: o código do widget não alcança o app, seus arquivos nem a rede.
- **Uma boa caixa de ferramentas.** Listar, ler, buscar, gravar e editar arquivos; tamanho de pastas; busca na web e leitura de páginas; comandos de shell.
- **Você no controle.** Gravações, edições e acesso a URLs pedem confirmação (configurável). Comandos de shell **sempre** pedem: você vê o comando, uma explicação em linguagem simples e a pasta, e permite ou nega. O agente é informado da sua decisão.
- **Sessões salvas** a cada resposta, para continuar depois pela tela inicial.
- **Onboarding de `AGENTS.md`.** Em uma pasta sem o arquivo, o agente oferece uma entrevista sobre o projeto e o escreve. Se já existir, ele é usado como instruções do projeto.
- **Interface em português.**

## Começando

1. Copie `harness.py` e a pasta `pyharness/` para o seu computador.
2. Abra um terminal na pasta onde você quer que as sessões sejam salvas e rode:

   ```
   python harness.py
   ```

   (No Windows, `py harness.py` também funciona.) O navegador abre o app.
3. Na tela inicial:
   1. **Login**: entre com a sua conta ChatGPT.
   2. **Escolher diretório**: escolha a pasta do projeto em que o agente pode trabalhar.
   3. **Iniciar**: fica habilitado quando os dois passos estão prontos.
4. Converse. No cabeçalho, troque modelo/nível, use **Status** para ver o uso, **Nova conversa** para recomeçar e **Configuração** para voltar à tela inicial.

As conversas anteriores aparecem em "Sessões anteriores" na tela inicial. Ficam como JSON em `myPyHarnessSessions/`, dentro da pasta de onde você iniciou o programa.

## Opções

| Opção | O que faz |
|---|---|
| `--dir PASTA` | Pré-seleciona a pasta do projeto (no `--cli`, padrão: pasta atual) |
| `--cli` | Chat no terminal em vez da interface web |
| `--model NOME` | Modelo inicial (padrão: o primeiro da sua conta; ou variável `HARNESS_MODEL`) |
| `--effort low\|medium\|high` | Nível de raciocínio inicial |
| `--mode ask\|auto` | `ask` (padrão) confirma gravações e acesso a URLs; `auto` não. Comandos sempre confirmam |
| `--port N` / `--no-browser` | Porta da interface / não abrir o navegador |
| `--login` / `--logout` | Apenas entrar / sair |

## Segurança

- **Sandbox de pasta para as ferramentas de arquivo.** Todo caminho é resolvido (links simbólicos, junções, `..`) e precisa ficar dentro da pasta escolhida. O código do próprio harness e as sessões salvas são somente leitura para o agente.
- **Rede.** `fetch_url` só faz GET e bloqueia localhost e endereços privados, inclusive em redirecionamentos.
- **Widgets.** O HTML escrito pelo modelo roda em um iframe isolado, com origem opaca e uma CSP que bloqueia qualquer requisição de rede; scripts só podem carregar bibliotecas de cdnjs e jsDelivr.
- **Interface local.** Escuta apenas em `127.0.0.1`, exige um token aleatório por execução e valida o cabeçalho `Host`.
- **Credenciais.** Os tokens de login ficam em `~/.pyharness/auth.json`.
- **O que *não* tem sandbox:** comandos de shell. Eles rodam com as suas permissões e podem mexer em qualquer lugar do computador. A única proteção é a sua aprovação: leia o comando em si, não só a explicação. Cuidado também com *prompt injection* vindo de páginas da web lidas pelo agente.

## Bom saber

- Sem vínculo com a OpenAI. Login, lista de modelos e status de uso usam o mesmo fluxo e endpoints não documentados do Codex CLI, então podem mudar sem aviso. Use conforme os termos do seu plano.
- Desenvolvido e testado no Linux. Windows é um objetivo, mas ainda não foi exercitado.
- O login precisa da porta `localhost:1455` livre por um minuto.
- As sessões salvas contêm o histórico das conversas: trate-as como privadas (aqui elas estão no `.gitignore`).

## Desenvolvimento

```
python -m unittest discover -s tests
```

Estrutura: `harness.py` (entrada), `pyharness/` (`auth`, `llm`, `agent`, `tools`, `server` + `ui.html`, `sessions`, `status`), `tests/`.

## Licença

[Apache License 2.0](LICENSE).
