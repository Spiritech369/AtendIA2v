# Advisor-first Multiturn Simulation

## Executive Summary

- cases_total: `10`
- cases_passed: `9`
- cases_failed: `1`
- average_naturalidad: `4.9`
- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`

## Case Matrix

| case | title | pass/fail | final_stage | naturalidad | repeticion | keyword_sospechoso | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| case_01 | Ubicacion + Adventure + buro | pass | cliente_potencial | 5 | no | no | ok |
| case_02 | R4 con antiguedad e ingreso informal | pass | handoff | 5 | no | no | ok |
| case_03 | Selecciona la primera despues de opciones | pass | handoff | 5 | no | no | ok |
| case_04 | Contado U5 | pass | handoff | 5 | no | no | ok |
| case_05 | Cambio de moto despues de cotizar | fail | handoff | 4 | si | no | repetition_detected |
| case_06 | Ok despues de cotizacion | pass | handoff | 5 | no | no | ok |
| case_07 | Documentos antes de elegir moto | pass | handoff | 5 | no | no | ok |
| case_08 | Cliente manda documento real | pass | handoff | 5 | no | no | ok |
| case_09 | Pide humano Francisco | pass | handoff | 5 | no | no | ok |
| case_10 | Ubicacion + precio + requisitos | pass | handoff | 5 | no | no | ok |

## Good Response Examples

- `case_01`: Estamos en Monterrey; te puedo orientar por aqui antes de pasarte a sucursal. Si tienes buro se revisa, pero no te prometo aprobacion; lo correcto es verlo con tu perfil.
- `case_02`: Necesito consultar los requisitos vigentes antes de pedirte documentos concretos. Te lo reviso para darte la lista correcta.
- `case_03`: Te puedo mostrar estas opciones: Adventure Elite 150 CC, R4 250 CC, U5 150 CC. Si dices 'la primera', tomo esa referencia exacta del catalogo.
- `case_04`: De contado, la U5 150 CC queda en $38,900. Te lo dejo como cotizacion activa para que no tengamos que recalcularla de memoria.
- `case_05`: Necesito consultar los requisitos vigentes antes de pedirte documentos concretos. Te lo reviso para darte la lista correcta.
- `case_06`: Necesito consultar los requisitos vigentes antes de pedirte documentos concretos. Te lo reviso para darte la lista correcta.
- `case_07`: Para documentos, de base ocupas INE, Comprobante de domicilio. Cuando elijas modelo te digo si aplica algo adicional.
- `case_08`: Tomo R4 250 CC como modelo de referencia; ahora vemos si te conviene contado o credito.
- `case_09`: Te paso con Francisco o con una persona del equipo para revisarlo directo.
- `case_10`: Tomo tu mensaje y reviso el siguiente paso con el contexto actual.

## Robotic Responses

- none