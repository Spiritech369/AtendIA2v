# Provider Repetition Audit

- entries_total: `3`
- exact_response_repeat: `1`
- same_slot_question_repeated: `0`
- quote_repeated_without_user_asking: `0`
- requirements_repeated_without_user_asking: `0`
- guard_fallback_repeated: `0`
- generic_cta_repeated: `0`
- advisor_next_action_stuck: `0`
- composer_ignored_new_user_signal: `2`

## adv_18 turn 4 - exact_response_repeat
- customer_message: `y la otra cuanto?`
- similarity: `0.0`
- advisor_next_best_action: `handoff`
- latest_customer_act: `None`
- suspected_root_cause: Final assistant message matched the previous assistant message exactly.
- previous: `Para cotizarte bien, dime que modelo quieres o elige una de las opciones.`
- current: `Para cotizarte bien, dime que modelo quieres o elige una de las opciones.`

## adv_24 turn 5 - composer_ignored_new_user_signal
- customer_message: `cotizame`
- similarity: `0.0`
- advisor_next_best_action: `handoff`
- latest_customer_act: `None`
- suspected_root_cause: Advisor or Composer did not incorporate the latest customer signal.
- previous: `Perfecto, tomo tu antiguedad laboral y seguimos con la validacion.`
- current: `Para cotizarte bien, dime que modelo quieres o elige una de las opciones.`

## adv_28 turn 4 - composer_ignored_new_user_signal
- customer_message: `cotiza`
- similarity: `0.0`
- advisor_next_best_action: `handoff`
- latest_customer_act: `None`
- suspected_root_cause: Advisor or Composer did not incorporate the latest customer signal.
- previous: `Perfecto, tomo ese dato de ingresos y avanzo con el siguiente paso.`
- current: `Para cotizarte bien, dime que modelo quieres o elige una de las opciones.`
