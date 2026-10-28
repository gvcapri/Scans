"""Gera os PDFs de exemplo usados na demonstração do LexScan.

Uso:  python scripts/make_samples.py
Cria em ./samples:
  * peticao_escaneada.pdf  — texto virado imagem (precisa de OCR), 1 página
  * contrato.pdf           — PDF nasceu-digital (com camada de texto)
  * contrato_v2.pdf        — versão alterada (para o comparador da Fase 4)
  * dados_sensiveis.pdf    — dados reais de teste (CPF, telefone...) p/ redação
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"


def make_scanned(path: Path) -> None:
    """Página A4 a 300 DPI com texto desenhado (e levemente inclinado)."""
    lines = [
        "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA 2ª VARA CÍVEL",
        "",
        "AUTOR: Maria da Silva — CPF 123.456.789-00",
        "REU: Empresa Exemplo Ltda — CNPJ 12.345.678/0001-90",
        "",
        "PETIÇÃO INICIAL — AÇÃO DE COBRANÇA",
        "",
        "Processo CNJ: 0000001-10.2026.8.01.0001",
        "Advogada: Joana Souza — OAB/DF 123456",
        "E-mail: contado@escritorio.adv.br — Tel (61) 99999-0000",
        "",
        "VEXA OS AUTOS, pois estão presentes os pressupostos de admissibilidade.",
    ]
    w, h = 2480, 3508  # A4 @ 300 DPI
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 58)
        font_bold = ImageFont.truetype("arialbd.ttf", 64)
    except OSError:
        font = font_bold = ImageFont.load_default()

    y = 300
    for i, line in enumerate(lines):
        draw.text((200, y), line, fill="black", font=font_bold if i in (0, 4) else font)
        y += 150

    img = img.rotate(1.5, fillcolor="white", resample=Image.BICUBIC)  # deskew
    img.save(path, "PDF", resolution=300)


def make_digital(path: Path, version: str, extra_clauses: list[str]) -> None:
    """PDF com camada de texto selecionável."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(60, 80), "CONTRATO DE PRESTAÇÃO DE SERVIÇOS", fontsize=16)
    page.insert_text(pymupdf.Point(60, 110), f"Versão: {version}", fontsize=11)
    y = 160
    for clause in extra_clauses:
        page.insert_text(pymupdf.Point(60, y), clause, fontsize=11)
        y += 26
    doc.save(path)
    doc.close()


def make_sensitive(path: Path) -> None:
    """PDF nasceu-digital com dados sensíveis p/ exercitar a redação (Fase 3)."""
    lines = [
        "RECLAMACAO TRABALHISTA - DADOS DA PARTE",
        "Nome: Joao Pereira da Silva",
        "CPF: 529.982.247-25",
        "RG: 12.345.678-9",
        "E-mail: cliente@escritorio.adv.br",
        "Telefone: (11) 98765-4321",
        "Endereco: Rua das Flores, 123 - Sao Paulo/SP",
        "Banco: Agencia 1234 Conta 56789-0",
        "Cartao: 4111 1111 1111 1111",
    ]
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for line in lines:
        page.insert_text(pymupdf.Point(72, y), line, fontsize=12)
        y += 34
    doc.save(path)
    doc.close()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    make_scanned(OUT / "peticao_escaneada.pdf")
    make_digital(
        OUT / "contrato.pdf",
        "1.0",
        [
            "CLÁUSULA 1 — O objeto do contrato é a prestação de serviços jurídicos.",
            "CLÁUSULA 2 — O honorário advocatício é de R$ 5.000,00 por mês.",
            "CLÁUSULA 3 — O prazo de vigência é de 12 (doze) meses.",
        ],
    )
    make_digital(
        OUT / "contrato_v2.pdf",
        "2.0",
        [
            "CLÁUSULA 1 — O objeto do contrato é a prestação de serviços jurídicos.",
            "CLÁUSULA 2 — O honorário advocatício é de R$ 6.500,00 por mês.",
            "CLÁUSULA 3 — O prazo de vigência é de 24 (vinte e quatro) meses.",
            "CLÁUSULA 4 — A rescisão deve ser comunicada com 30 dias de antecedência.",
        ],
    )
    make_sensitive(OUT / "dados_sensiveis.pdf")
    print(f"Amostras gravadas em {OUT}")


if __name__ == "__main__":
    main()
