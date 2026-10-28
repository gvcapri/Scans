"""Verificação no navegador dos fluxos principais do LexScan (Fases 1 a 3).

Abre o app com Playwright/Chromium, executa de verdade:
  1. painel + catálogo de ferramentas
  2. envio de PDF escaneado → OCR → download do PDF pesquisável
  3. envio de PDF digital → Blindado (com camada de texto) → download
  4. mesclagem com reordenação → download do PDF final
  5. divisão por intervalo → arquivos por parte
  6. conversão PDF → TXT
  7. compressão com perfil de tribunal + PDF/A + perfil salvo
  8. redação com revisão manual (desmarca um dado) → PDF com tarja
  9. metadados jurídicos (CNJ, partes) + renomeação
 10. numeração Bates + marca d'água
 11. sumário/índice com nomeação de anexos + bookmarks
 12. certificado de integridade (SHA-256 + ICP-Brasil)
 13. histórico, tema escuro e layout mobile
e grava evidências em ./evidence.

Uso (com backend :8000 e frontend :5173 rodando):
    python scripts/e2e_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "evidence"
DL = EVID / "downloads"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'OK ' if ok else 'FAL'}] {name}{f' — {detail}' if detail else ''}")


def _latest_job(page, kind: str) -> dict | None:
    jobs = page.request.get(f"{BASE}/api/jobs").json()
    done = [j for j in jobs if j["kind"] == kind and j["status"] == "done"]
    return done[0] if done else None


def _download(page, file_id: str, filename: str) -> bytes:
    resp = page.request.get(f"{BASE}/api/files/{file_id}/download")
    body = resp.body()
    (DL / filename).write_bytes(body)
    return body


def main() -> int:
    # Windows: console em cp1252 quebra ao imprimir setas/acentos
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    EVID.mkdir(exist_ok=True)
    DL.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 920}, locale="pt-BR")

        # ---------------------------------------------------------- 1. painel
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("text=Ferramentas")
        tools = page.request.get(f"{BASE}/api/meta/tools").json()["tools"]
        cards = page.locator("button:has-text('Disponível')").count()
        check("painel abre com o catálogo", cards >= 11, f"{cards} ferramentas ativas de {len(tools)}")
        page.screenshot(path=str(EVID / "01-painel.png"), full_page=True)

        # ------------------------------------------------------------- 2. OCR
        page.locator("button:has-text('OCR')").first.click()
        page.wait_for_selector("text=OCR de documentos")
        page.set_input_files(
            "input[type=file]", str(ROOT / "samples" / "peticao_escaneada.pdf")
        )
        page.wait_for_selector("text=SHA-256", timeout=20000)
        check("upload do PDF escaneado", True, "peticao_escaneada.pdf")
        page.screenshot(path=str(EVID / "02-ocr-opcoes.png"), full_page=True)

        page.get_by_role("button", name="Executar OCR").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("OCR conclui e oferece download", True)
        page.screenshot(path=str(EVID / "03-ocr-concluido.png"), full_page=True)

        job = _latest_job(page, "ocr")
        check("job de OCR terminou com progresso 100%", bool(job and job["progress"] == 100))
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "ocr_resultado.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            text = "".join(pg.get_text() for pg in doc).upper()
            doc.close()
            achou = any(k in text for k in ("VARA", "PETI", "CÍVEL", "CIVEL", "EXCELENT", "REU"))
            check("PDF de saída tem camada de texto pesquisável", achou, f"{len(text)} caracteres extraídos")
            check("prévia do texto aparece na tela", page.locator("pre").count() > 0)
        else:
            check("PDF de saída baixado", False, "sem saída no job")

        # --------------------------------------------------------- 3. blindar
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('PDF Blindado')").first.click()
        page.wait_for_selector("text=PDF Blindado")
        page.set_input_files("input[type=file]", str(ROOT / "samples" / "contrato.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.get_by_label("Manter camada de texto pesquisável").check()
        page.screenshot(path=str(EVID / "04-blindado-opcoes.png"), full_page=True)

        page.get_by_role("button", name="Blindar documento").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("blindagem conclui e oferece download", True)
        page.screenshot(path=str(EVID / "05-blindado-concluido.png"), full_page=True)

        job = _latest_job(page, "blind")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "contrato_blindado.pdf")
            import pikepdf
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            images = doc[0].get_images(full=True)
            texto = doc[0].get_text().strip()
            doc.close()
            check("página virou imagem (achatada)", len(images) >= 1, f"{len(images)} imagem(ns)")
            check("camada invisível permite busca", "CONTRATO" in texto.upper(), f"{len(texto)} chars")

            with pikepdf.open(DL / "contrato_blindado.pdf") as pdf:
                docinfo = [k for k in pdf.docinfo.keys() if k != "/ID"]
                check("metadados removidos", not docinfo and "/Metadata" not in pdf.Root, f"DocInfo={docinfo}")
                check("sem JavaScript/ação automática", "/OpenAction" not in pdf.Root and "/AA" not in pdf.Root)
        else:
            check("PDF blindado baixado", False, "sem saída no job")

        # ------------------------------------------- 4. mesclar (Fase 2)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Mesclar')").first.click()
        page.wait_for_selector("text=Mesclar PDFs")
        page.set_input_files(
            "input[type=file]",
            [
                str(ROOT / "samples" / "contrato.pdf"),
                str(ROOT / "samples" / "peticao_escaneada.pdf"),
            ],
        )
        page.wait_for_selector("text=SHA-256", timeout=20000)
        setas = page.locator("button:has-text('↓ Descer')").count()
        check("mesclagem aceita dois arquivos", setas == 2, f"{setas} na fila")
        # reordena: o escaneado (2º) passa a ser o 1º
        page.locator("button:has-text('↓ Descer')").first.click()
        page.wait_for_timeout(200)
        page.get_by_role("button", name="Mesclar arquivos").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("mesclagem conclui e oferece download", True)
        page.screenshot(path=str(EVID / "06-mesclar.png"), full_page=True)

        job = _latest_job(page, "merge")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "mesclado.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            paginas = doc.page_count
            escaneado_primeiro = bool(doc[0].get_images(full=True))
            toc = doc.get_toc()
            doc.close()
            check("arquivo final tem as 2 páginas", paginas == 2, f"{paginas} páginas")
            check("reordenação respeitada", escaneado_primeiro)
            check("sumário por arquivo de origem", len(toc) >= 2, f"{len(toc)} itens")
        else:
            check("mescla baixada", False, "sem saída no job")

        # --------------------------------------------------- 5. dividir
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Dividir')").first.click()
        page.wait_for_selector("text=Dividir PDF")
        page.set_input_files("input[type=file]", str(DL / "mesclado.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.fill("#split-ranges", "1-1,2-2")
        page.get_by_role("button", name="Dividir documento").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("divisão por intervalo conclui", True)
        page.screenshot(path=str(EVID / "07-dividir.png"), full_page=True)

        job = _latest_job(page, "split")
        partes = len(job["output_file_ids"]) if job else 0
        check("um arquivo por intervalo pedido", partes == 2, f"{partes} arquivos")

        # ------------------------------------------------- 6. converter
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Converter')").first.click()
        page.wait_for_selector("text=Converter documentos")
        page.set_input_files("input[type=file]", str(ROOT / "samples" / "contrato.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.get_by_label("Formato de saída").select_option("txt")
        page.get_by_role("button", name="Converter", exact=True).click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("conversão PDF → TXT conclui", True)
        page.screenshot(path=str(EVID / "08-converter.png"), full_page=True)

        job = _latest_job(page, "convert")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "contrato_convertido.txt")
            texto = body.decode("utf-8", errors="replace").upper()
            check("texto extraído do PDF digital", "CONTRATO" in texto, f"{len(body)} bytes")
        else:
            check("TXT baixado", False, "sem saída no job")

        # ---------------------------------------------- 7. comprimir
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Compressor')").first.click()
        page.wait_for_selector("text=Compressor de PDF")
        page.set_input_files("input[type=file]", str(DL / "mesclado.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        check(
            "perfis de tribunal listados",
            page.get_by_label("Perfil de tribunal").locator("option").count() >= 5,
        )
        page.get_by_label("Perfil de tribunal").select_option(label="PJe — 10 MB")
        page.fill("#limit-mb", "0.1")  # limite apertado: força divisão se precisar
        # limpa perfil de execuções anteriores (mesmo nome devolveria 409)
        existentes = page.request.get(f"{BASE}/api/presets?tool=compress").json()[
            "presets"
        ]
        for preset in existentes:
            if preset["name"] == "E2E 100 KB" and not preset["builtin"]:
                page.request.delete(f"{BASE}/api/presets/{preset['id']}")
        page.fill("#preset-name", "E2E 100 KB")
        page.get_by_role("button", name="Salvar perfil").click()
        page.wait_for_selector("text=salvo.", timeout=15000)
        check("perfil personalizado salvo", True, "E2E 100 KB")
        page.get_by_label("Gerar PDF/A-2b").check()
        page.screenshot(path=str(EVID / "09-comprimir-opcoes.png"), full_page=True)

        page.get_by_role("button", name="Comprimir", exact=True).click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("compressão conclui e oferece download", True)
        page.screenshot(path=str(EVID / "10-comprimir-concluido.png"), full_page=True)

        job = _latest_job(page, "compress")
        if job and job["output_file_ids"]:
            limite = int(0.1 * 1024 * 1024)
            total_paginas = 0
            dentro = True
            import pymupdf
            import pikepdf

            for index, file_id in enumerate(job["output_file_ids"]):
                body = _download(page, file_id, f"comprimido_parte_{index + 1}.pdf")
                dentro = dentro and len(body) <= limite
                doc = pymupdf.open(stream=body, filetype="pdf")
                total_paginas += doc.page_count
                doc.close()
            check("todas as partes dentro do limite de 0,1 MB", dentro,
                 f"{len(job['output_file_ids'])} arquivo(s)")
            check("nenhuma página se perdeu", total_paginas == 2, f"{total_paginas} páginas")
            with pikepdf.open(DL / "comprimido_parte_1.pdf") as pdf:
                check("PDF/A gravado (OutputIntent)", "/OutputIntents" in pdf.Root)
        else:
            check("PDF comprimido baixado", False, "sem saída no job")

        # ------------------------------------------ 8. redigir (Fase 3)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Tarjar / Redigir')").first.click()
        page.wait_for_selector("text=Aplicar redação")
        page.set_input_files(
            "input[type=file]", str(ROOT / "samples" / "dados_sensiveis.pdf")
        )
        page.wait_for_selector("text=Revisão antes de aplicar", timeout=20000)
        page.wait_for_selector("text=ocorrência", timeout=20000)
        grupos = page.locator("li:has-text('CPF')").count()
        check("revisão lista os dados sensíveis", grupos >= 1, f"{grupos} grupo(s) de CPF")
        # desmarca o telefone: ele deve sobreviver à tarja
        page.locator("li:has-text('Telefone')").get_by_role("checkbox").uncheck()
        page.screenshot(path=str(EVID / "11-redacao-revisao.png"), full_page=True)

        page.get_by_role("button", name="Aplicar redação").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("redação conclui e oferece download", True)
        page.screenshot(path=str(EVID / "12-redacao-concluido.png"), full_page=True)

        job = _latest_job(page, "redact")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "redigido.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            texto = "".join(pg.get_text() for pg in doc)
            doc.close()
            check(
                "CPF e e-mail removidos de forma irreversível",
                "529.982.247-25" not in texto
                and "cliente@escritorio.adv.br" not in texto,
                f"{len(texto)} caracteres restantes",
            )
            check("telefone desmarcado permanece intacto", "(11) 98765-4321" in texto)
        else:
            check("PDF redigido baixado", False, "sem saída no job")

        # --------------------------------------- 9. metadados (Fase 3)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Dados da peça')").first.click()
        page.wait_for_selector("text=Gravar metadados")
        page.set_input_files("input[type=file]", str(ROOT / "samples" / "contrato.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.fill("#meta-cnj", "0000001-10.2026.8.01.0001")
        page.fill("#meta-tipo", "Contestação")
        page.fill("#meta-autor", "João Pereira")
        page.fill("#meta-reu", "Transportes Ltda")
        page.fill("#meta-data", "2026-10-28")
        page.screenshot(path=str(EVID / "13-metadados-opcoes.png"), full_page=True)
        page.get_by_role("button", name="Gravar metadados").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("metadados gravados com download", True)

        job = _latest_job(page, "metadata")
        if job and job["output_file_ids"]:
            out_id = job["output_file_ids"][0]
            nome = page.request.get(f"{BASE}/api/files/{out_id}").json()["name"]
            check(
                "arquivo renomeado com o CNJ",
                nome.startswith("Contestação - 0000001"),
                nome[:70],
            )
            body = _download(page, out_id, "contestacao_cnj.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            meta = doc.metadata
            doc.close()
            check(
                "metadados no PDF (título + partes)",
                "Contestação" in (meta.get("title") or "")
                and meta.get("author") == "João Pereira x Transportes Ltda",
                str(meta.get("title")),
            )
        else:
            check("PDF com metadados baixado", False, "sem saída no job")

        # --------------------------------------- 10. numerar (Fase 3)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Numerar / Bates')").first.click()
        page.wait_for_selector("text=Numerar documento")
        page.set_input_files("input[type=file]", str(DL / "mesclado.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.get_by_label("Estilo").select_option("bates")
        page.fill("#bates-prefix", "E2E")
        page.fill("#wm-text", "USO JUDICIAL")
        page.screenshot(path=str(EVID / "14-numerar-opcoes.png"), full_page=True)
        page.get_by_role("button", name="Numerar documento").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("numeração Bates concluída", True)

        job = _latest_job(page, "number")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "numerado.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            texto = "".join(pg.get_text() for pg in doc)
            paginas = doc.page_count
            doc.close()
            check(
                "Bates em todas as páginas",
                texto.count("E2E") == paginas,
                f"{texto.count('E2E')} carimbo(s) em {paginas} página(s)",
            )
            check("marca d'água aplicada", "USO JUDICIAL" in texto)
        else:
            check("PDF numerado baixado", False, "sem saída no job")

        # --------------------------------------- 11. sumário (Fase 3)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Sumário e índice')").first.click()
        page.wait_for_selector("text=Gerar sumário")
        page.set_input_files("input[type=file]", str(ROOT / "samples" / "contrato.pdf"))
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.get_by_role("button", name="+ Adicionar anexo").click()
        page.get_by_label("Nome do anexo 1").fill("ANEXO I — Procuração")
        page.get_by_label("Página do anexo 1").fill("1")
        page.screenshot(path=str(EVID / "15-sumario-opcoes.png"), full_page=True)
        page.get_by_role("button", name="Gerar sumário").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("sumário/índice gerado", True)

        job = _latest_job(page, "outline")
        if job and job["output_file_ids"]:
            body = _download(page, job["output_file_ids"][0], "sumario.pdf")
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            toc = doc.get_toc()
            indice = doc[0].get_text()
            paginas = doc.page_count
            doc.close()
            check("página de índice inserida no início", paginas == 2, f"{paginas} páginas")
            check(
                "bookmarks criados",
                len(toc) >= 2 and toc[0][1] == "ÍNDICE",
                f"{len(toc)} item(ns)",
            )
            check("anexo nomeado no índice", "ANEXO I" in indice)
        else:
            check("PDF com sumário baixado", False, "sem saída no job")

        # ----------------------------------- 12. certificado (Fase 3)
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.locator("button:has-text('Certificado de integridade')").first.click()
        page.wait_for_selector("text=Emitir certificado")
        page.set_input_files(
            "input[type=file]",
            [
                str(ROOT / "samples" / "contrato.pdf"),
                str(ROOT / "samples" / "dados_sensiveis.pdf"),
            ],
        )
        page.wait_for_selector("text=SHA-256", timeout=20000)
        page.wait_for_selector("button:has-text('Remover')", timeout=20000)
        removiveis = page.locator("button:has-text('Remover')").count()
        check("certificado aceita dois arquivos", removiveis == 2, f"{removiveis} na fila")
        page.fill("#cert-emitente", "E2E Automação")
        page.fill("#cert-obs", "Processo 0000001-10.2026.8.01.0001")
        page.get_by_role("button", name="Emitir certificado").click()
        page.wait_for_selector("a:has-text('Baixar')", timeout=240000)
        check("certificado emitido com download", True)
        page.screenshot(path=str(EVID / "16-certificado.png"), full_page=True)

        job = _latest_job(page, "integrity")
        if job and job["output_file_ids"]:
            import hashlib

            body = _download(page, job["output_file_ids"][0], "certificado_integridade.pdf")
            esperados = [
                hashlib.sha256((ROOT / "samples" / nome).read_bytes()).hexdigest()
                for nome in ("contrato.pdf", "dados_sensiveis.pdf")
            ]
            import pymupdf

            doc = pymupdf.open(stream=body, filetype="pdf")
            texto = "".join(pg.get_text() for pg in doc).replace("\n", "")
            doc.close()
            check(
                "SHA-256 dos dois arquivos no certificado",
                all(h in texto for h in esperados),
                f"{len(esperados)} hashes",
            )
            check("estrutura ICP-Brasil declarada", "ICP-Brasil" in texto)
        else:
            check("certificado baixado", False, "sem saída no job")

        # ------------------------------------------------- 13. histórico
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.get_by_role("button", name="Histórico", exact=True).click()
        page.wait_for_selector("text=Processamentos")
        page.wait_for_selector("li:has-text('Concluído')", timeout=20000)
        itens = page.locator("li:has-text('Concluído')").count()
        check("histórico lista os processamentos", itens >= 11, f"{itens} concluídos")
        page.screenshot(path=str(EVID / "17-historico.png"), full_page=True)

        # ------------------------------------------------------- 5. tema/mobile
        page.get_by_role("button", name="Painel", exact=True).click()
        page.wait_for_selector("text=Ferramentas")
        page.get_by_role("button", name="🌙 Escuro").click()
        page.wait_for_timeout(400)
        escuro = page.evaluate("() => document.documentElement.classList.contains('dark')")
        check("tema escuro aplica", escuro)
        page.screenshot(path=str(EVID / "18-tema-escuro.png"), full_page=True)
        page.get_by_role("button", name="☀️ Claro").click()

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, locale="pt-BR")
        mobile.goto(BASE, wait_until="networkidle")
        mobile.wait_for_selector("text=Ferramentas")
        mobile.screenshot(path=str(EVID / "19-mobile.png"), full_page=True)
        check("layout responsivo renderiza no mobile", True)

        browser.close()

    print("\nResumo:")
    falhas = 0
    for nome, ok, detalhe in RESULTS:
        print(f"  [OK ] {nome}{f' ({detalhe})' if detalhe else ''}" if ok else f"  [FAL] {nome}{f' ({detalhe})' if detalhe else ''}")
        if not ok:
            falhas += 1
    print(f"\n{len(RESULTS) - falhas}/{len(RESULTS)} verificações OK")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
