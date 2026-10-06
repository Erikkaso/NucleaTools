#include "wakeword_detector.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "esp_log.h"
#include "model/nuclea_model.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {
constexpr const char* kTag = "WAKEWORD_MODEL";
alignas(16) uint8_t kTensorArena[52 * 1024];
tflite::MicroMutableOpResolver<10> kResolver;
bool kResolverReady = false;

bool HasExpectedInput(const TfLiteTensor* input) {
    return input != nullptr && input->type == kTfLiteInt8 && input->dims != nullptr &&
           input->dims->size == 4 && input->dims->data[0] == 1 && input->dims->data[1] == 13 &&
           input->dims->data[2] == 49 && input->dims->data[3] == 1 &&
           input->bytes == 13 * 49 && input->params.scale > 0.0f;
}

bool HasExpectedOutput(const TfLiteTensor* output) {
    return output != nullptr && output->type == kTfLiteInt8 && output->dims != nullptr &&
           output->dims->size == 2 && output->dims->data[0] == 1 &&
           output->dims->data[1] == 2 && output->bytes == 2 && output->params.scale > 0.0f;
}
}

esp_err_t WakewordDetector::Init() {
    const tflite::Model* model = tflite::GetModel(kNucleaModelData);
    if (model == nullptr || model->version() != TFLITE_SCHEMA_VERSION) return ESP_ERR_INVALID_VERSION;
    if (!kResolverReady) {
        kResolver.AddConv2D();
        kResolver.AddDepthwiseConv2D();
        kResolver.AddMaxPool2D();
        kResolver.AddFullyConnected();
        kResolver.AddReshape();
        kResolver.AddAdd();
        kResolver.AddMul();
        kResolver.AddMean();
        kResolver.AddRelu();
        kResolver.AddSoftmax();
        kResolverReady = true;
    }
    interpreter_ = new tflite::MicroInterpreter(model, kResolver, kTensorArena, sizeof(kTensorArena));
    if (interpreter_ == nullptr || interpreter_->AllocateTensors() != kTfLiteOk) return ESP_ERR_NO_MEM;
    const TfLiteTensor* input = interpreter_->input(0);
    const TfLiteTensor* output = interpreter_->output(0);
    if (!HasExpectedInput(input) || !HasExpectedOutput(output)) {
        ESP_LOGE(kTag, "Contrato dos tensores TFLite inesperado");
        return ESP_ERR_INVALID_STATE;
    }
    input_scale_ = input->params.scale;
    input_zero_point_ = input->params.zero_point;
    ready_ = true;
    ESP_LOGI(kTag,
             "Modelo pronto: %u bytes input(scale=%.9g zp=%d bytes=%u) output(scale=%.9g zp=%d bytes=%u)",
             static_cast<unsigned>(kNucleaModelDataSize), static_cast<double>(input_scale_),
             input_zero_point_, static_cast<unsigned>(input->bytes),
             static_cast<double>(output->params.scale), output->params.zero_point,
             static_cast<unsigned>(output->bytes));
    return ESP_OK;
}

esp_err_t WakewordDetector::Infer(const int8_t* features, float* score) {
    if (!ready_ || features == nullptr || score == nullptr) return ESP_ERR_INVALID_STATE;
    TfLiteTensor* input = interpreter_->input(0);
    TfLiteTensor* output = interpreter_->output(0);
    const auto bounds = std::minmax_element(features, features + input->bytes);
    last_input_min_ = *bounds.first;
    last_input_max_ = *bounds.second;
    std::memcpy(input->data.int8, features, input->bytes);
    if (interpreter_->Invoke() != kTfLiteOk) return ESP_FAIL;
    last_background_output_ = output->data.int8[0];
    last_wakeword_output_ = output->data.int8[1];
    *score = (output->data.int8[1] - output->params.zero_point) * output->params.scale;
    if (!std::isfinite(*score)) return ESP_ERR_INVALID_RESPONSE;
    *score = std::clamp(*score, 0.0f, 1.0f);
    return ESP_OK;
}
